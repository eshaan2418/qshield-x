// QSX-UF decoder core. Implements DECISIONS.md D1 with a fully parallel edge/vertex fabric and
// LANES-wide parity/activity scans. Cycle behaviour is mirrored exactly by qsx::HwModel.
//
// FSM (one work cycle per state visit unless noted; `cycles` counts work cycles):
//   IDLE --start--> LABEL (repeat until labels stable, inclusive) -> PAR (NCH) -> ACT (NCH) -> CHK
//   CHK: no active cluster -> DINIT; rounds == max_rounds -> DONE(TIMEOUT); else GROW -> LABEL
//   DINIT -> DIST (repeat until stable, inclusive) -> PEH -> PEEL (until every vertex done) -> DONE
//   Any work state: cycle_budget != 0 && cycles == cycle_budget -> DONE(WATCHDOG)
// PIPE=1 registers the grown-edge vector and the LABEL/DIST convergence flags (shorter critical path):
//   each LABEL and each DIST phase then takes one extra cycle (the no-change iteration is observed one
//   cycle later). qsx::HwModel reproduces both variants (HwParams::pipe).
// Outputs `corr`/`obs` are forced to zero unless status == OK.
`default_nettype none
`include "qsx_graph_defs.svh"

module qsx_uf_core #(
  parameter int LANES = 8,
  parameter int PIPE = 0,
  parameter int RB = 8,
  parameter int CB = 20
) (
  input  wire                      clk,
  input  wire                      rst_n,
  input  wire                      start,
  input  wire [`QSX_V-1:0]         defect_in,
  input  wire [`QSX_E*`QSX_TB-1:0] thr_in,
  input  wire [RB-1:0]             max_rounds,
  input  wire [CB-1:0]             cycle_budget,
  output wire                      busy,
  output wire                      done,
  output reg  [2:0]                status,
  output wire                      obs,
  output wire [`QSX_E-1:0]         corr,
  output reg  [CB-1:0]             cycles,
  output reg  [RB-1:0]             rounds
);
  localparam int V  = `QSX_V;
  localparam int E  = `QSX_E;
  localparam int VB = `QSX_VB;
  localparam int EB = `QSX_EB;
  localparam int TB = `QSX_TB;
  localparam int MD = `QSX_MD;
  localparam int SB = `QSX_SB;
  localparam int DB = `QSX_DB;
  localparam int NCH = (V + LANES - 1) / LANES;
  localparam int IB = (NCH <= 1) ? 1 : $clog2(NCH);
  localparam [DB-1:0] INF = {DB{1'b1}};

  // Constant-table lookups below zero-extend narrow table fields into int localparams.
  /* verilator lint_off WIDTHEXPAND */
  /* verilator lint_off UNUSEDPARAM */
  `include "qsx_graph_tables.svh"
  /* verilator lint_on UNUSEDPARAM */

  localparam [3:0] S_IDLE = 4'd0, S_LABEL = 4'd1, S_PAR = 4'd2, S_ACT = 4'd3, S_CHK = 4'd4,
                   S_GROW = 4'd5, S_DINIT = 4'd6, S_DIST = 4'd7, S_PEH = 4'd8, S_PEEL = 4'd9,
                   S_DONE = 4'd10;
  localparam [2:0] ST_OK = 3'd0, ST_TIMEOUT = 3'd1, ST_PARITY = 3'd2, ST_WATCHDOG = 3'd3;

  reg  [3:0]      state;
  reg  [V-1:0]    defect;
  reg  [E*TB-1:0] support;
  reg  [V*VB-1:0] label;
  reg  [V-1:0]    par_acc, bnd_acc, active, vbnd, vdone, peh_b;
  reg             any_act, perr;
  reg  [V*DB-1:0] dst;
  reg  [V*MD-1:0] peh;
  reg  [E-1:0]    corr_r;
  reg  [IB-1:0]   idx;
  reg  [E-1:0]    grown_r;     // PIPE=1 only
  reg             lchg, lfirst; // PIPE=1 convergence pipeline

  assign busy = (state != S_IDLE);
  assign done = (state == S_DONE);
  assign corr = (status == ST_OK) ? corr_r : {E{1'b0}};
  assign obs  = (status == ST_OK) & (^(corr_r & G_OBS0));

  // ------------------------------------------------------------------ edge fabric
  wire [E-1:0]    grown;
  wire [E-1:0]    grown_c;
  wire [E-1:0]    grown_n;     // grown vector after the GROW update (PIPE=1 register input)
  wire [E*TB-1:0] support_n;
  assign grown = (PIPE != 0) ? grown_r : grown_c;
  genvar e, v, k, j, c;
  generate
    for (e = 0; e < E; e = e + 1) begin : g_edge
      localparam int EU = G_EU[e*VB +: VB];
      localparam int EV = G_EV[e*VB +: VB];
      localparam bit EBND = G_EBND[e];
      wire [TB-1:0] s = support[e*TB +: TB];
      wire [TB-1:0] t = thr_in[e*TB +: TB];
      wire [1:0]    inc;
      if (EBND) begin : g_b
        assign inc = {1'b0, active[EU]};
      end else begin : g_i
        assign inc = {1'b0, active[EU]} + {1'b0, active[EV]};
      end
      wire [TB:0] sum = {1'b0, s} + {{(TB-1){1'b0}}, inc};
      assign grown_c[e] = (s == t);
      wire [TB-1:0] sn = (sum >= {1'b0, t}) ? t : sum[TB-1:0];
      assign support_n[e*TB +: TB] = sn;
      assign grown_n[e] = (sn == t);
    end
  endgenerate

  // ------------------------------------------------------------------ vertex fabric
  wire [V-1:0]    bgrown;
  wire [V*VB-1:0] label_n;
  wire [V*DB-1:0] dst_n, dst_init;
  wire [V*MD-1:0] peh_n;
  wire [V-1:0]    peh_b_n, fire, acc, isroot;
  generate
    for (v = 0; v < V; v = v + 1) begin : g_vert
      localparam bit HASB = G_HAS_BEDGE[v];
      localparam int BE   = G_BEDGE[v*EB +: EB];
      if (HASB) begin : g_hb
        assign bgrown[v] = grown[BE];
      end else begin : g_nb
        assign bgrown[v] = 1'b0;
      end
      wire [VB-1:0] lv = label[v*VB +: VB];
      wire [DB-1:0] dv = dst[v*DB +: DB];
      wire [(MD+1)*VB-1:0] lcand;
      wire [(MD+1)*DB-1:0] dcand;
      wire [MD-1:0] pcand, child, cdone, ccorr;
      assign lcand[MD*VB +: VB] = lv;
      assign dcand[MD*DB +: DB] = dv;
      for (k = 0; k < MD; k = k + 1) begin : g_slot
        localparam bit SV = G_SLOT_VALID[v*MD+k];
        localparam int SE = G_SLOT_E[(v*MD+k)*EB +: EB];
        localparam int SW = G_SLOT_W[(v*MD+k)*VB +: VB];
        localparam int SK = G_SLOT_BACK[(v*MD+k)*SB +: SB];
        if (SV) begin : g_v
          wire [DB-1:0] dw = dst[SW*DB +: DB];
          assign lcand[k*VB +: VB] = grown[SE] ? label[SW*VB +: VB] : {VB{1'b1}};
          assign dcand[k*DB +: DB] = (grown[SE] && dw != INF) ? dw + 1'b1 : INF;
          assign pcand[k] = grown[SE] && (dw == dv - 1'b1);
          assign child[k] = peh[SW*MD + SK];
          assign cdone[k] = vdone[SW];
          assign ccorr[k] = corr_r[SE];
        end else begin : g_x
          assign lcand[k*VB +: VB] = {VB{1'b1}};
          assign dcand[k*DB +: DB] = INF;
          assign pcand[k] = 1'b0;
          assign child[k] = 1'b0;
          assign cdone[k] = 1'b1;
          assign ccorr[k] = 1'b0;
        end
      end
      qsx_min_tree #(.N(MD+1), .W(VB)) u_lmin (.in(lcand), .out(label_n[v*VB +: VB]));
      qsx_min_tree #(.N(MD+1), .W(DB)) u_dmin (.in(dcand), .out(dst_n[v*DB +: DB]));
      // canonical forest
      assign dst_init[v*DB +: DB] = vbnd[v] ? (bgrown[v] ? {{(DB-1){1'b0}}, 1'b1} : INF)
                                             : ((lv == v) ? {DB{1'b0}} : INF);
      wire dv_ok = (dv != {DB{1'b0}}) && (dv != INF) && !bgrown[v];
      wire [MD-1:0] pc = dv_ok ? pcand : {MD{1'b0}};
      assign peh_n[v*MD +: MD] = pc & (~pc + 1'b1);  // lowest-index slot
      assign peh_b_n[v] = bgrown[v] && (dv != {DB{1'b0}});
      // peeling
      assign fire[v]   = !vdone[v] && (&(~child | cdone));
      assign acc[v]    = defect[v] ^ (^(child & ccorr));
      assign isroot[v] = !peh_b[v] && !(|peh[v*MD +: MD]);
    end
  endgenerate

  wire [E-1:0] corr_set, corr_val;
  generate
    for (e = 0; e < E; e = e + 1) begin : g_ecorr
      localparam int EU = G_EU[e*VB +: VB];
      localparam int EV = G_EV[e*VB +: VB];
      localparam bit EBND = G_EBND[e];
      localparam int KU = G_EU_SLOT[e*SB +: SB];
      localparam int KV = G_EV_SLOT[e*SB +: SB];
      if (EBND) begin : g_b
        assign corr_set[e] = fire[EU] && peh_b[EU];
        assign corr_val[e] = acc[EU];
      end else begin : g_i
        wire su = fire[EU] && peh[EU*MD + KU];
        wire sv = fire[EV] && peh[EV*MD + KV];
        assign corr_set[e] = su || sv;
        assign corr_val[e] = su ? acc[EU] : acc[EV];
      end
    end
  endgenerate

  // ------------------------------------------------------------------ lanes
  wire [LANES-1:0]       lane_valid, lane_def, lane_bg, lane_act, lane_vb;
  wire [LANES*VB-1:0]    lane_lab;
  generate
    for (j = 0; j < LANES; j = j + 1) begin : g_lane
      wire [NCH*VB-1:0] o_lab;
      wire [NCH-1:0]    o_def, o_bg, o_val;
      for (c = 0; c < NCH; c = c + 1) begin : g_opt
        if (c*LANES + j < V) begin : g_in
          assign o_lab[c*VB +: VB] = label[(c*LANES+j)*VB +: VB];
          assign o_def[c] = defect[c*LANES+j];
          assign o_bg[c]  = bgrown[c*LANES+j];
          assign o_val[c] = 1'b1;
        end else begin : g_out
          assign o_lab[c*VB +: VB] = {VB{1'b0}};
          assign o_def[c] = 1'b0;
          assign o_bg[c]  = 1'b0;
          assign o_val[c] = 1'b0;
        end
      end
      wire [VB-1:0] lab = o_lab[idx*VB +: VB];
      assign lane_lab[j*VB +: VB] = lab;
      assign lane_valid[j] = o_val[idx];
      assign lane_def[j]   = o_def[idx];
      assign lane_bg[j]    = o_bg[idx];
      assign lane_act[j]   = par_acc[lab] && !bnd_acc[lab];
      assign lane_vb[j]    = bnd_acc[lab];
    end
  endgenerate

  wire [V-1:0] hit_p, hit_b;
  generate
    for (v = 0; v < V; v = v + 1) begin : g_root
      wire [LANES-1:0] mp, mb;
      for (j = 0; j < LANES; j = j + 1) begin : g_l
        wire m = lane_valid[j] && (lane_lab[j*VB +: VB] == v);
        assign mp[j] = m && lane_def[j];
        assign mb[j] = m && lane_bg[j];
      end
      assign hit_p[v] = ^mp;
      assign hit_b[v] = |mb;
    end
  endgenerate

  // ------------------------------------------------------------------ control
  wire work = (state != S_IDLE) && (state != S_DONE);
  wire wd   = work && (cycle_budget != {CB{1'b0}}) && (cycles == cycle_budget);
  wire [V-1:0] vdone_n = vdone | fire;
  wire perr_n = perr || (|(fire & isroot & acc));
  integer i;

  always @(posedge clk) begin
    if (!rst_n) begin
      state  <= S_IDLE;
      status <= ST_OK;
      cycles <= {CB{1'b0}};
      rounds <= {RB{1'b0}};
      corr_r <= {E{1'b0}};
      idx    <= {IB{1'b0}};
      any_act <= 1'b0;
      perr   <= 1'b0;
    end else if (wd) begin
      status <= ST_WATCHDOG;
      state  <= S_DONE;
    end else begin
      if (work) cycles <= cycles + 1'b1;
      case (state)
        S_IDLE: if (start) begin
          defect  <= defect_in;
          support <= {E*TB{1'b0}};
          for (i = 0; i < E; i = i + 1) grown_r[i] <= (thr_in[i*TB +: TB] == {TB{1'b0}});
          lfirst  <= 1'b1;
          lchg    <= 1'b1;
          for (i = 0; i < V; i = i + 1) label[i*VB +: VB] <= i[VB-1:0];
          cycles  <= {CB{1'b0}};
          rounds  <= {RB{1'b0}};
          status  <= ST_OK;
          perr    <= 1'b0;
          corr_r  <= {E{1'b0}};
          state   <= S_LABEL;
        end
        S_LABEL: begin
          label  <= label_n;
          lchg   <= (label_n != label);
          lfirst <= 1'b0;
          if ((PIPE == 0) ? (label_n == label) : (!lfirst && !lchg)) begin
            state   <= S_PAR;
            idx     <= {IB{1'b0}};
            par_acc <= {V{1'b0}};
            bnd_acc <= {V{1'b0}};
            lfirst  <= 1'b1;
          end
        end
        S_PAR: begin
          par_acc <= par_acc ^ hit_p;
          bnd_acc <= bnd_acc | hit_b;
          if (idx == IB'(NCH-1)) begin
            idx     <= {IB{1'b0}};
            any_act <= 1'b0;
            state   <= S_ACT;
          end else idx <= idx + 1'b1;
        end
        S_ACT: begin
          for (i = 0; i < V; i = i + 1)
            if (idx == IB'(i / LANES)) begin
              active[i] <= lane_act[i % LANES];
              vbnd[i]   <= lane_vb[i % LANES];
            end
          any_act <= any_act | (|(lane_valid & lane_act));
          if (idx == IB'(NCH-1)) state <= S_CHK;
          else idx <= idx + 1'b1;
        end
        S_CHK: begin
          if (!any_act) state <= S_DINIT;
          else if (rounds == max_rounds) begin
            status <= ST_TIMEOUT;
            state  <= S_DONE;
          end else state <= S_GROW;
        end
        S_GROW: begin
          support <= support_n;
          grown_r <= grown_n;
          rounds  <= rounds + 1'b1;
          state   <= S_LABEL;
        end
        S_DINIT: begin
          dst    <= dst_init;
          lfirst <= 1'b1;
          state <= S_DIST;
        end
        S_DIST: begin
          dst    <= dst_n;
          lchg   <= (dst_n != dst);
          lfirst <= 1'b0;
          if ((PIPE == 0) ? (dst_n == dst) : (!lfirst && !lchg)) state <= S_PEH;
        end
        S_PEH: begin
          peh   <= peh_n;
          peh_b <= peh_b_n;
          vdone <= {V{1'b0}};
          state <= S_PEEL;
        end
        S_PEEL: begin
          for (i = 0; i < E; i = i + 1)
            if (corr_set[i]) corr_r[i] <= corr_val[i];
          vdone <= vdone_n;
          perr  <= perr_n;
          if (&vdone_n) begin
            status <= perr_n ? ST_PARITY : ST_OK;
            state  <= S_DONE;
          end else if (!(|fire)) begin  // structurally unreachable; fail closed
            status <= ST_WATCHDOG;
            state  <= S_DONE;
          end
        end
        S_DONE: state <= S_IDLE;
        default: state <= S_IDLE;
      endcase
    end
  end
  /* verilator lint_on WIDTHEXPAND */
endmodule
`default_nettype wire

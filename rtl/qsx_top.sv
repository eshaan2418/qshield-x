// QShield-X accelerator top: AXI-Stream in -> frame FIFO -> QSX-UF core -> AXI-Stream out.
//
// Output frame: beat 0 = {8'h5A, status[3:0], 3'b0, obs, tag[15:0]}; if OUT_CORR, followed by
// CW = ceil(E/32) beats of the correction bitmap (edge e at bit e%32 of beat 1+e/32). tlast marks
// the final beat. Status: 0 OK, 1 TIMEOUT, 2 PARITY_ERROR, 3 WATCHDOG, 4 FRAME_ERROR, 5 CFG_INVALID.
// For any status != OK the obs bit and all correction beats are zero.
`default_nettype none
`include "qsx_graph_defs.svh"
module qsx_top #(
  parameter int LANES    = 8,
  parameter int NBUF     = 4,
  parameter int OUT_CORR = 1,
  parameter int RB       = 8,
  parameter int CB       = 20
) (
  input  wire        clk,
  input  wire        rst_n,
  input  wire [31:0] s_axis_tdata,
  input  wire        s_axis_tvalid,
  output wire        s_axis_tready,
  input  wire        s_axis_tlast,
  output wire [31:0] m_axis_tdata,
  output wire        m_axis_tvalid,
  input  wire        m_axis_tready,
  output wire        m_axis_tlast,
  input  wire        cfg_valid,
  output wire        cfg_ready,
  input  wire [11:0] cfg_addr,
  input  wire [31:0] cfg_wdata,
  output wire        cfg_open,
  output wire        cfg_ok,
  output wire        cfg_err,
  output reg  [31:0] stat_frames_in,
  output reg  [31:0] stat_frames_out,
  output wire [CB-1:0] stat_last_cycles
);
  localparam int V  = `QSX_V;
  localparam int E  = `QSX_E;
  localparam int TB = `QSX_TB;
  localparam int W  = (V + 31) / 32;
  localparam int CW = (E + 31) / 32;
  localparam int BB = $clog2(W+1);
  localparam int OB = (OUT_CORR != 0) ? $clog2(CW+1) : 1;

  // ---------------------------------------------------------------- ingress
  wire          rd_avail, rd_ferr;
  reg  [BB-1:0] rd_beat;
  wire [31:0]   rd_data;
  reg           rd_pop;
  wire [$clog2(NBUF):0] fifo_count;
  qsx_ingress #(.W(W), .NBUF(NBUF)) u_in (
    .clk(clk), .rst_n(rst_n), .s_tdata(s_axis_tdata), .s_tvalid(s_axis_tvalid),
    .s_tready(s_axis_tready), .s_tlast(s_axis_tlast), .rd_avail(rd_avail), .rd_ferr(rd_ferr),
    .rd_beat(rd_beat), .rd_data(rd_data), .rd_pop(rd_pop), .count(fifo_count));

  // ---------------------------------------------------------------- config + core
  wire [E*TB-1:0] thr;
  wire [RB-1:0]   max_rounds;
  wire [CB-1:0]   cycle_budget;
  reg             core_start;
  wire            core_busy, core_done, core_obs;
  wire [2:0]      core_status;
  wire [E-1:0]    core_corr;
  wire [RB-1:0]   core_rounds;
  qsx_cfg #(.RB(RB), .CB(CB)) u_cfg (
    .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_addr(cfg_addr),
    .cfg_wdata(cfg_wdata), .core_busy(core_busy || core_start), .thr(thr), .max_rounds(max_rounds),
    .cycle_budget(cycle_budget), .cfg_open(cfg_open), .cfg_ok(cfg_ok), .cfg_err(cfg_err));

  /* verilator lint_off UNUSEDSIGNAL */
  reg [W*32-1:0] defect_buf;  // bits >= V are padding
  /* verilator lint_on UNUSEDSIGNAL */
  qsx_uf_core #(.LANES(LANES), .RB(RB), .CB(CB)) u_core (
    .clk(clk), .rst_n(rst_n), .start(core_start), .defect_in(defect_buf[V-1:0]), .thr_in(thr),
    .max_rounds(max_rounds), .cycle_budget(cycle_budget), .busy(core_busy), .done(core_done),
    .status(core_status), .obs(core_obs), .corr(core_corr), .cycles(stat_last_cycles),
    .rounds(core_rounds));

  // ---------------------------------------------------------------- dispatcher
  localparam [2:0] D_IDLE = 3'd0, D_LOAD = 3'd1, D_GATE = 3'd2, D_WAIT = 3'd3, D_HOLD = 3'd4;
  reg [2:0]    dstate;
  reg [BB-1:0] cap;            // beat being captured (rd_data valid for beat cap)
  reg          cap_v;
  reg [15:0]   cur_tag;
  reg          cur_ferr;
  reg [3:0]    pend_status;    // status to emit from D_HOLD
  reg          pend_from_core;

  // egress
  reg          eg_busy;
  reg [OB-1:0] eg_beat;
  reg [15:0]   eg_tag;
  reg [3:0]    eg_status;
  reg          eg_obs;
  reg [CW*32-1:0] eg_corr;
  wire eg_last = (OUT_CORR == 0) || (eg_beat == OB'(CW));
  wire eg_fire = m_axis_tvalid && m_axis_tready;

  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin
      dstate <= D_IDLE;
      rd_beat <= {BB{1'b0}};
      rd_pop <= 1'b0;
      cap_v <= 1'b0;
      cap <= {BB{1'b0}};
      core_start <= 1'b0;
      stat_frames_in <= 32'd0;
      cur_tag <= 16'd0;
      cur_ferr <= 1'b0;
      pend_status <= 4'd0;
      pend_from_core <= 1'b0;
    end else begin
      rd_pop <= 1'b0;
      core_start <= 1'b0;
      case (dstate)
        D_IDLE: if (rd_avail && !rd_pop) begin
          rd_beat <= {BB{1'b0}};
          cap_v   <= 1'b0;
          dstate  <= D_LOAD;
        end
        D_LOAD: begin
          // issue reads for beats 0..W; capture one cycle later
          if (rd_beat != BB'(W)) rd_beat <= rd_beat + 1'b1;
          cap   <= rd_beat;
          cap_v <= 1'b1;
          if (cap_v) begin
            if (cap == {BB{1'b0}}) cur_tag <= rd_data[15:0];
            for (i = 0; i < W; i = i + 1)
              if (cap == BB'(i + 1)) defect_buf[i*32 +: 32] <= rd_data;
            if (cap == BB'(W)) begin
              cur_ferr <= rd_ferr;
              rd_pop   <= 1'b1;
              cap_v    <= 1'b0;
              dstate   <= D_GATE;
            end
          end
        end
        D_GATE: begin
          // decide: malformed -> FRAME_ERROR; config open or host writing -> wait; invalid -> CFG_INVALID
          if (cur_ferr) begin
            pend_status <= 4'd4;
            pend_from_core <= 1'b0;
            dstate <= D_HOLD;
          end else if (!cfg_open && !cfg_valid) begin
            if (!cfg_ok) begin
              pend_status <= 4'd5;
              pend_from_core <= 1'b0;
              dstate <= D_HOLD;
            end else begin
              core_start <= 1'b1;
              dstate <= D_WAIT;
            end
          end
        end
        D_WAIT: if (core_done) begin
          pend_from_core <= 1'b1;
          dstate <= D_HOLD;
        end
        D_HOLD: if (!eg_busy) begin
          stat_frames_in <= stat_frames_in + 1'b1;
          dstate <= D_IDLE;
        end
        default: dstate <= D_IDLE;
      endcase
    end
  end

  // egress load happens in the D_HOLD cycle where !eg_busy
  wire eg_load = (dstate == D_HOLD) && !eg_busy && rst_n;
  always @(posedge clk) begin
    if (!rst_n) begin
      eg_busy <= 1'b0;
      eg_beat <= {OB{1'b0}};
      stat_frames_out <= 32'd0;
      eg_tag <= 16'd0;
      eg_status <= 4'd0;
      eg_obs <= 1'b0;
    end else if (eg_load) begin
      eg_busy   <= 1'b1;
      eg_beat   <= {OB{1'b0}};
      eg_tag    <= cur_tag;
      eg_status <= pend_from_core ? {1'b0, core_status} : pend_status;
      eg_obs    <= pend_from_core && core_obs && (core_status == 3'd0);
      if (OUT_CORR != 0) begin
        eg_corr <= {CW*32{1'b0}};
        if (pend_from_core && core_status == 3'd0) eg_corr[E-1:0] <= core_corr;
      end
    end else if (eg_fire) begin
      if (eg_last) begin
        eg_busy <= 1'b0;
        stat_frames_out <= stat_frames_out + 1'b1;
      end else eg_beat <= eg_beat + 1'b1;
    end
  end

  wire [31:0] hdr = {8'h5A, eg_status, 3'b000, eg_obs, eg_tag};
  generate
    if (OUT_CORR != 0) begin : g_oc
      wire [32*(CW+1)-1:0] eg_words = {eg_corr, hdr};
      assign m_axis_tdata = eg_words[eg_beat*32 +: 32];
    end else begin : g_noc
      assign m_axis_tdata = hdr;
    end
  endgenerate
  assign m_axis_tvalid = eg_busy;
  assign m_axis_tlast  = eg_busy && eg_last;

  wire unused_ok = &{1'b0, core_rounds, fifo_count};
endmodule
`default_nettype wire

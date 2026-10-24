// Formal harness for qsx_top (properties M3-P1..P6, see formal/README.md).
`default_nettype none
`include "qsx_graph_defs.svh"
module top_formal (
  input wire clk, input wire rst_n,
  input wire [31:0] s_axis_tdata, input wire s_axis_tvalid, input wire s_axis_tlast,
  input wire m_axis_tready,
  input wire cfg_valid, input wire [11:0] cfg_addr, input wire [31:0] cfg_wdata
);
  localparam int E = `QSX_E;
  localparam int CW = (E + 31) / 32;
  localparam int NW = (E + 7) / 8;
  wire s_axis_tready, m_axis_tvalid, m_axis_tlast, cfg_ready, cfg_open, cfg_ok, cfg_err;
  wire [31:0] m_axis_tdata, fin, fout;
  wire [19:0] lastc;
  qsx_top #(.LANES(8), .NBUF(2), .OUT_CORR(1)) dut (
    .clk(clk), .rst_n(rst_n), .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid),
    .s_axis_tready(s_axis_tready), .s_axis_tlast(s_axis_tlast), .m_axis_tdata(m_axis_tdata),
    .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready), .m_axis_tlast(m_axis_tlast),
    .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
    .cfg_open(cfg_open), .cfg_ok(cfg_ok), .cfg_err(cfg_err), .stat_frames_in(fin),
    .stat_frames_out(fout), .stat_last_cycles(lastc), .f_inflight(inflight), .f_cfg_written(cfg_written),
    .f_in_hdr_next(dut_in_hdr), .f_out_hdr_next(dut_out_hdr),
    .f_eg_status(dut_eg_status), .f_cfg_bad(cfg_bad), .f_slot_tag(slot_tag), .f_rslot(rslot), .f_cur_tag(cur_tag),
    .f_eg_tag(eg_tag), .f_disp_holds_o(disp_holds), .f_eg_pending_o(eg_pending));
  wire [31:0] slot_tag;
  wire rslot, disp_holds, eg_pending;
  wire [15:0] cur_tag, eg_tag;
  wire [3:0] dut_eg_status;
  wire cfg_bad;
  wire dut_in_hdr, dut_out_hdr;
  wire [NW-1:0] cfg_written;
  wire [3:0] inflight;

  reg f_init = 1'b0;
  always @(posedge clk) f_init <= 1'b1;
  always @(*) if (!f_init) assume (!rst_n);
  reg past_valid = 1'b0;   // a reset has been applied
  always @(posedge clk) if (!rst_n) past_valid <= 1'b1;
  wire live = past_valid && rst_n;

  // ------------------------------------------------ environment assumptions (AXIS/cfg masters)
  reg p_sv, p_sr, p_cv, p_cr, p_mv, p_mr, p_rst;
  reg [31:0] p_sd, p_md, p_cd;
  reg p_sl, p_ml;
  reg [11:0] p_ca;
  always @(posedge clk) begin
    p_rst <= rst_n;
    p_sv <= s_axis_tvalid; p_sr <= s_axis_tready; p_sd <= s_axis_tdata; p_sl <= s_axis_tlast;
    p_cv <= cfg_valid; p_cr <= cfg_ready; p_ca <= cfg_addr; p_cd <= cfg_wdata;
    p_mv <= m_axis_tvalid; p_mr <= m_axis_tready; p_md <= m_axis_tdata; p_ml <= m_axis_tlast;
  end
  always @(*) if (live && p_rst && p_sv && !p_sr)
    assume (s_axis_tvalid && s_axis_tdata == p_sd && s_axis_tlast == p_sl);
  always @(*) if (live && p_rst && p_cv && !p_cr)
    assume (cfg_valid && cfg_addr == p_ca && cfg_wdata == p_cd);

  // ------------------------------------------------ P1: AXI-Stream master compliance
  always @(*) if (live && p_rst && p_mv && !p_mr)
    assert (m_axis_tvalid && m_axis_tdata == p_md && m_axis_tlast == p_ml);
  always @(*) if (live) assert (!m_axis_tlast || m_axis_tvalid);

  // ------------------------------------------------ P2/P3: round tag + no spurious output
  // Non-saturating observers: bal = headers received - headers emitted; one frame, picked
  // nondeterministically when its header is accepted, is tracked by its position among the older
  // frames still inside the accelerator.
  wire s_fire = s_axis_tvalid && s_axis_tready;
  wire m_fire = m_axis_tvalid && m_axis_tready;
  reg in_hdr, out_hdr;           // next beat is a header
  reg [3:0] bal;
  reg tracked;
  reg [3:0] tpos;
  reg [15:0] ttag;
  (* anyseq *) wire pick;
  reg out_bad;                   // current output frame carries a non-OK status
  wire in_h  = s_fire && in_hdr;
  wire out_h = m_fire && out_hdr;
  always @(posedge clk) begin
    if (!rst_n) begin
      in_hdr <= 1'b1; out_hdr <= 1'b1; bal <= 4'd0; tracked <= 1'b0; out_bad <= 1'b0;
    end else begin
      bal <= bal + {3'b0, in_h} - {3'b0, out_h};
      if (s_fire) in_hdr <= s_axis_tlast;
      if (m_fire) out_hdr <= m_axis_tlast;
      if (out_h) out_bad <= (m_axis_tdata[23:20] != 4'd0);
      if (tracked && out_h) begin
        if (tpos == 4'd0) tracked <= 1'b0;
        else tpos <= tpos - 1'b1;
      end
      if (in_h && pick && !(tracked && !(out_h && tpos == 4'd0))) begin
        tracked <= 1'b1;
        ttag <= s_axis_tdata[15:0];
        tpos <= bal - {3'b0, out_h};
      end
    end
  end
  wire m_is_hdr = m_axis_tvalid && out_hdr;
  // framing correspondence between the harness observers and the DUT
  always @(*) if (live) assert (in_hdr == dut_in_hdr && out_hdr == dut_out_hdr);
  always @(*) if (live && !out_hdr) assert (m_axis_tvalid && out_bad == (dut_eg_status != 4'd0));
  // P3: every received header is either emitted or still inside the accelerator (no loss, no
  // duplication, no spurious output frame)
  always @(*) if (live) assert (bal == inflight);
  always @(*) if (live && m_is_hdr) assert (bal != 4'd0);
  // P2 (inductive form): the tracked frame, wherever it is inside the accelerator, carries its tag.
  // Oldest first: egress (header pending) -> dispatcher -> FIFO slots from rslot -> partial slot.
  wire [3:0] k1 = tpos - {3'b0, eg_pending};
  wire [3:0] k2 = k1 - {3'b0, disp_holds};
  wire       sslot = rslot + k2[0];
  always @(*) if (live && tracked) begin
    assert (tpos < bal);
    if (eg_pending && tpos == 4'd0) assert (eg_tag == ttag);
    else if (disp_holds && k1 == 4'd0) assert (cur_tag == ttag);
    else assert (slot_tag[sslot*16 +: 16] == ttag);
  end
  // P2: when the tracked frame's response header is presented, it carries the tracked tag
  always @(*) if (live && tracked && m_is_hdr && tpos == 4'd0) assert (m_axis_tdata[15:0] == ttag);
  // P4: header well-formed; non-OK frames carry obs=0 and an all-zero correction
  always @(*) if (live && m_is_hdr) begin
    assert (m_axis_tdata[31:24] == 8'h5A);
    assert (m_axis_tdata[23:20] <= 4'd5);
    if (m_axis_tdata[23:20] != 4'd0) assert (m_axis_tdata[16] == 1'b0);
  end
  always @(*) if (live && m_axis_tvalid && !out_hdr && out_bad) assert (m_axis_tdata == 32'd0);

  // ------------------------------------------------ P5: atomic configuration (reference model)
  wire c_fire = cfg_valid && cfg_ready;
  reg h_open, h_ok, h_bad;
  reg [NW-1:0] h_written;
  localparam [3:0] TMAX = 4'((1 << `QSX_TB) - 1);
  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin h_open <= 1'b0; h_ok <= 1'b1; h_written <= 0; h_bad <= 1'b0; end
    else if (c_fire) begin
      if (cfg_addr == 12'h000 && cfg_wdata[1:0] == 2'd1) begin
        h_open <= 1'b1; h_ok <= 1'b0; h_written <= 0; h_bad <= 1'b0;
      end else if (cfg_addr == 12'h000 && cfg_wdata[1:0] == 2'd2 && h_open) begin
        h_open <= 1'b0; h_ok <= (&h_written) && !h_bad;
      end else if (h_open && cfg_addr[11:8] == 4'h1 && {24'd0, cfg_addr[7:0]} < NW) begin
        for (i = 0; i < NW; i = i + 1) if ({24'd0, cfg_addr[7:0]} == i) h_written[i] <= 1'b1;
        // reference rule: every threshold nibble that maps to an edge must be in [1, 2^TB-1]
        for (i = 0; i < 8; i = i + 1)
          if ({24'd0, cfg_addr[7:0]} * 8 + i < E && (cfg_wdata[i*4 +: 4] == 4'd0 || cfg_wdata[i*4 +: 4] > TMAX))
            h_bad <= 1'b1;
      end
    end
  end
  always @(*) if (live) assert (cfg_ok == h_ok && cfg_open == h_open);
  always @(*) if (live && h_open) assert (cfg_written == h_written && cfg_bad == h_bad);
  // P6: no output status OK is possible while configuration is invalid and no frame was decoded before
  // (covered more precisely by the internal assertion in qsx_top: core start => cfg_ok && !cfg_open)

  // reachability witnesses (cover)
  always @(*) if (live) cover (m_is_hdr && m_axis_tdata[23:20] == 4'd0 && tracked && tpos == 4'd0);
  always @(*) if (live) cover (m_is_hdr && m_axis_tdata[23:20] == 4'd5);
  always @(*) if (live) cover (m_is_hdr && m_axis_tdata[23:20] == 4'd4);
  wire unused = &{1'b0, fin, fout, lastc, cfg_err, CW[0]};
endmodule
`default_nettype wire

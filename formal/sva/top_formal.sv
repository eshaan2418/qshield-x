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
    .stat_frames_out(fout), .stat_last_cycles(lastc));

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
  wire s_fire = s_axis_tvalid && s_axis_tready;
  wire m_fire = m_axis_tvalid && m_axis_tready;
  reg in_hdr, out_hdr;           // next beat is a header
  reg [3:0] in_n, out_n;         // header counters (saturating)
  (* anyconst *) wire [3:0] sel;
  reg [15:0] sel_tag;
  reg sel_seen;
  reg [3:0] out_status;
  reg out_bad;                   // current output frame carries a non-OK status
  always @(posedge clk) begin
    if (!rst_n) begin
      in_hdr <= 1'b1; out_hdr <= 1'b1; in_n <= 0; out_n <= 0; sel_seen <= 1'b0; out_bad <= 1'b0;
    end else begin
      if (s_fire) begin
        if (in_hdr) begin
          if (in_n == sel) begin sel_tag <= s_axis_tdata[15:0]; sel_seen <= 1'b1; end
          if (in_n != 4'hf) in_n <= in_n + 1'b1;
        end
        in_hdr <= s_axis_tlast;
      end
      if (m_fire) begin
        if (out_hdr) begin
          if (out_n != 4'hf) out_n <= out_n + 1'b1;
          out_bad <= (m_axis_tdata[23:20] != 4'd0);
        end
        out_hdr <= m_axis_tlast;
      end
    end
  end
  wire m_is_hdr = m_axis_tvalid && out_hdr;
  // P3: an output header k is only produced after input header k was received
  always @(*) if (live && m_is_hdr && in_n != 4'hf) assert (out_n < in_n);
  // P2: output k carries the tag of input k
  always @(*) if (live && m_is_hdr && out_n == sel && sel != 4'hf) assert (sel_seen && m_axis_tdata[15:0] == sel_tag);
  // P4: header well-formed; non-OK frames carry obs=0 and an all-zero correction
  always @(*) if (live && m_is_hdr) begin
    assert (m_axis_tdata[31:24] == 8'h5A);
    assert (m_axis_tdata[23:20] <= 4'd5);
    if (m_axis_tdata[23:20] != 4'd0) assert (m_axis_tdata[16] == 1'b0);
  end
  always @(*) if (live && m_axis_tvalid && !out_hdr && out_bad) assert (m_axis_tdata == 32'd0);

  // ------------------------------------------------ P5: atomic configuration (reference model)
  wire c_fire = cfg_valid && cfg_ready;
  reg h_open, h_ok;
  reg [NW-1:0] h_written;
  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin h_open <= 1'b0; h_ok <= 1'b1; h_written <= 0; end
    else if (c_fire) begin
      if (cfg_addr == 12'h000 && cfg_wdata[1:0] == 2'd1) begin h_open <= 1'b1; h_ok <= 1'b0; h_written <= 0; end
      else if (cfg_addr == 12'h000 && cfg_wdata[1:0] == 2'd2 && h_open) begin h_open <= 1'b0; h_ok <= &h_written; end
      else if (h_open && cfg_addr[11:8] == 4'h1)
        for (i = 0; i < NW; i = i + 1) if ({24'd0, cfg_addr[7:0]} == i) h_written[i] <= 1'b1;
    end
  end
  always @(*) if (live) assert (cfg_ok == h_ok && cfg_open == h_open);
  // P6: no output status OK is possible while configuration is invalid and no frame was decoded before
  // (covered more precisely by the internal assertion in qsx_top: core start => cfg_ok && !cfg_open)

  // reachability witnesses (cover)
  always @(*) if (live) cover (m_is_hdr && m_axis_tdata[23:20] == 4'd0 && out_n == 1);
  always @(*) if (live) cover (m_is_hdr && m_axis_tdata[23:20] == 4'd5);
  always @(*) if (live) cover (m_is_hdr && m_axis_tdata[23:20] == 4'd4);
  wire unused = &{1'b0, fin, fout, lastc, cfg_err, CW[0]};
endmodule
`default_nettype wire

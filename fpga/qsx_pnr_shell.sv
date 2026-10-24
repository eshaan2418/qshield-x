// Place-and-route shell: exposes only the AXI-Stream and configuration ports of qsx_top so the
// design fits the LFE5U-85F CABGA381 I/O count. Debug statistics outputs are left unconnected (and
// therefore removed by synthesis); they are not part of the measured design.
`default_nettype none
module qsx_pnr_shell #(
  parameter int LANES = 8,
  parameter int NBUF = 4,
  parameter int OUT_CORR = 1
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
  output wire        cfg_err
);
  /* verilator lint_off PINCONNECTEMPTY */
  qsx_top #(.LANES(LANES), .NBUF(NBUF), .OUT_CORR(OUT_CORR)) u_top (
    .clk(clk), .rst_n(rst_n),
    .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
    .s_axis_tlast(s_axis_tlast), .m_axis_tdata(m_axis_tdata), .m_axis_tvalid(m_axis_tvalid),
    .m_axis_tready(m_axis_tready), .m_axis_tlast(m_axis_tlast), .cfg_valid(cfg_valid),
    .cfg_ready(cfg_ready), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata), .cfg_open(cfg_open),
    .cfg_ok(cfg_ok), .cfg_err(cfg_err), .stat_frames_in(), .stat_frames_out(), .stat_last_cycles());
  /* verilator lint_on PINCONNECTEMPTY */
endmodule
`default_nettype wire

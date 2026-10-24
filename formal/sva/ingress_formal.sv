// Formal wrapper: reset is asserted in the first cycle; the embedded assertions of qsx_ingress
// (rtl/qsx_ingress.sv, `ifdef FORMAL) are then checked for every subsequent cycle.
`default_nettype none
module ingress_formal #(parameter int W = 2, parameter int NBUF = 4) (
  input wire clk, input wire rst_n,
  input wire [31:0] s_tdata, input wire s_tvalid, input wire s_tlast,
  input wire [$clog2(W+1)-1:0] rd_beat, input wire rd_pop
);
  reg f_init = 1'b0;
  always @(posedge clk) f_init <= 1'b1;
  always @(*) if (!f_init) assume (!rst_n);
  wire s_tready, rd_avail, rd_ferr;
  wire [31:0] rd_data;
  wire [$clog2(NBUF):0] count;
  qsx_ingress #(.W(W), .NBUF(NBUF)) dut (.clk(clk), .rst_n(rst_n), .s_tdata(s_tdata), .s_tvalid(s_tvalid),
    .s_tready(s_tready), .s_tlast(s_tlast), .rd_avail(rd_avail), .rd_ferr(rd_ferr), .rd_beat(rd_beat),
    .rd_data(rd_data), .rd_pop(rd_pop), .count(count));
  // Data integrity of the committed head frame is covered by the top-level tag property.
  always @(*) if (f_init && rst_n) assert (rd_avail == (count != 0));
endmodule
`default_nettype wire

// Formal harness for the real QSX-UF core (properties C1..C5, formal/README.md).
`default_nettype none
`include "qsx_graph_defs.svh"
module core_formal (
  input wire clk, input wire rst_n, input wire start,
  input wire [`QSX_V-1:0] defect_in,
  input wire [`QSX_E*`QSX_TB-1:0] thr_in,
  input wire [7:0] max_rounds, input wire [19:0] cycle_budget
);
  localparam int E = `QSX_E;
  wire busy, done, obs;
  wire [2:0] status;
  wire [E-1:0] corr;
  wire [19:0] cycles;
  wire [7:0] rounds;
  qsx_uf_core #(.LANES(8)) dut (.clk(clk), .rst_n(rst_n), .start(start), .defect_in(defect_in),
    .thr_in(thr_in), .max_rounds(max_rounds), .cycle_budget(cycle_budget), .busy(busy), .done(done),
    .status(status), .obs(obs), .corr(corr), .cycles(cycles), .rounds(rounds));
  reg f_init = 1'b0;
  always @(posedge clk) f_init <= 1'b1;
  always @(*) if (!f_init) assume (!rst_n);
  // environment: configuration is held stable while the core is busy (guaranteed by qsx_top, P6)
  reg [`QSX_E*`QSX_TB-1:0] p_thr;
  reg [7:0] p_mr;
  reg [19:0] p_cb;
  reg p_busy;
  always @(posedge clk) begin p_thr <= thr_in; p_mr <= max_rounds; p_cb <= cycle_budget; p_busy <= busy; end
  always @(*) if (rst_n && p_busy) assume (thr_in == p_thr && max_rounds == p_mr && cycle_budget == p_cb);
  // thresholds are never 0 (cfg writes only legal values; reset table is >= 1)
  genvar e;
  generate for (e = 0; e < E; e = e + 1) begin : g_thr
    always @(*) assume (thr_in[e*`QSX_TB +: `QSX_TB] != 0);
  end endgenerate

  // busy-cycle counter of the current decode (harness side)
  reg [20:0] run;
  always @(posedge clk) begin
    if (!rst_n) run <= 0;
    else if (!busy && start) run <= 0;
    else if (busy && !done) run <= run + 1'b1;
  end
  always @(*) if (rst_n) begin
    // C1: an invalid / timed-out result never carries a correction or a logical prediction
    if (done && status != 3'd0) assert (corr == {E{1'b0}} && !obs);
    // C2: the watchdog bounds the work cycles of every decode
    if (busy && cycle_budget != 20'd0) assert (cycles <= cycle_budget);
    // C3: status codes are defined
    assert (status <= 3'd3);
    // harness/DUT correspondence: every non-DONE busy cycle is a counted work cycle, except the single
    // watchdog-abort cycle
    // (scoped to watchdog-enabled operation; with cycle_budget == 0 the 20-bit counter could only wrap
    // after 2^20 work cycles, which exceeds the analytical worst case for max_rounds <= 255, see README)
    if (cycle_budget != 20'd0 && busy && !done) assert (run == {1'b0, cycles});
    if (cycle_budget != 20'd0 && done) assert (run == {1'b0, cycles} || run == {1'b0, cycles} + 21'd1);
    // C4: busy span is the counted work plus the start/done bookkeeping
    if (busy && cycle_budget != 20'd0) assert (run <= {1'b0, cycle_budget} + 21'd1);
  end
  // C5: done is a single-cycle pulse followed by idle
  reg p_done;
  always @(posedge clk) p_done <= done;
  always @(*) if (rst_n && p_done && f_init) assert (!done && !busy);
  always @(*) if (rst_n) cover (done && status == 3'd0 && corr != {E{1'b0}});
  always @(*) if (rst_n) cover (done && status == 3'd1);
  always @(*) if (rst_n) cover (done && status == 3'd3);
  wire unused = &{1'b0, rounds};
endmodule
`default_nettype wire

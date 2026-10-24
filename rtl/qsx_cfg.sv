// Configuration block with atomic session semantics.
//   word address map (cfg_addr):
//     0x000 CTRL       write 1 = BEGIN session, 2 = COMMIT
//     0x001 MAX_ROUNDS (RB bits)
//     0x002 BUDGET     (CB bits, 0 = watchdog disabled)
//     0x100+i THR[i]   eight 4-bit thresholds per word (low TB bits of each nibble used)
// After reset the block holds the built-in tables and cfg_valid=1. BEGIN clears the "written" map and
// raises cfg_open (the dispatcher starts no decode while open). COMMIT sets cfg_valid only if *every*
// THR word was written during the session; otherwise cfg_valid=0 and frames are answered CFG_INVALID.
// Writes are accepted (cfg_ready) only while the core is idle, so thresholds never change mid-decode.
// A threshold of 0 is outside the decoder semantics (DECISIONS D1: thr in [1, 2^TB-1]); a session that
// writes any zero threshold (or a value that does not fit in TB bits) commits as invalid.
`default_nettype none
`include "qsx_graph_defs.svh"
module qsx_cfg #(
  parameter int RB = 8,
  parameter int CB = 20,
  parameter [RB-1:0] MAX_ROUNDS_RST = {RB{1'b1}}
) (
  input  wire                      clk,
  input  wire                      rst_n,
  input  wire                      cfg_valid,
  output wire                      cfg_ready,
  input  wire [11:0]               cfg_addr,
  input  wire [31:0]               cfg_wdata,
  input  wire                      core_busy,
  output reg  [`QSX_E*`QSX_TB-1:0] thr,
  output reg  [RB-1:0]             max_rounds,
  output reg  [CB-1:0]             cycle_budget,
  output reg                       cfg_open,
  output reg                       cfg_ok,
  output reg                       cfg_err      // sticky: write outside a session or bad address
`ifdef FORMAL
  , output wire [(`QSX_E+7)/8-1:0] f_written
  , output wire f_bad_thr
`endif
);
  localparam int E  = `QSX_E;
  localparam int TB = `QSX_TB;
  localparam [3:0] TMAX = 4'((1 << TB) - 1);
  localparam int NW = (E + 7) / 8;
  reg [NW-1:0] written;
  reg          bad_thr;
  /* verilator lint_off UNUSEDPARAM */
  `include "qsx_graph_tables.svh"
  /* verilator lint_on UNUSEDPARAM */

`ifdef FORMAL
  assign f_written = written;
  assign f_bad_thr = bad_thr;
`endif
  assign cfg_ready = !core_busy;
  wire wr = cfg_valid && cfg_ready;
  wire is_thr = (cfg_addr[11:8] == 4'h1) && ({24'd0, cfg_addr[7:0]} < NW);
  integer i;

  always @(posedge clk) begin
    if (!rst_n) begin
      thr          <= G_THR;
      max_rounds   <= MAX_ROUNDS_RST;
      cycle_budget <= {CB{1'b0}};
      cfg_open     <= 1'b0;
      cfg_ok       <= 1'b1;
      cfg_err      <= 1'b0;
      written      <= {NW{1'b0}};
      bad_thr      <= 1'b0;
    end else if (wr) begin
      if (cfg_addr == 12'h000) begin
        if (cfg_wdata[1:0] == 2'd1) begin
          cfg_open <= 1'b1;
          cfg_ok   <= 1'b0;
          written  <= {NW{1'b0}};
          bad_thr  <= 1'b0;
        end else if (cfg_wdata[1:0] == 2'd2 && cfg_open) begin
          cfg_open <= 1'b0;
          cfg_ok   <= (&written) && !bad_thr;
        end else cfg_err <= 1'b1;
      end else if (!cfg_open) begin
        cfg_err <= 1'b1;
      end else if (cfg_addr == 12'h001) begin
        max_rounds <= cfg_wdata[RB-1:0];
      end else if (cfg_addr == 12'h002) begin
        cycle_budget <= cfg_wdata[CB-1:0];
      end else if (is_thr) begin
        for (i = 0; i < E; i = i + 1)
          if ({24'd0, cfg_addr[7:0]} == i / 8) thr[i*TB +: TB] <= cfg_wdata[(i % 8)*4 +: TB];
        for (i = 0; i < NW; i = i + 1)
          if ({24'd0, cfg_addr[7:0]} == i) written[i] <= 1'b1;
        for (i = 0; i < 8; i = i + 1)
          if ({24'd0, cfg_addr[7:0]} * 8 + i < E &&
              (cfg_wdata[i*4 +: 4] == 4'd0 || cfg_wdata[i*4 +: 4] > TMAX))
            bad_thr <= 1'b1;
      end else cfg_err <= 1'b1;
    end
  end
endmodule
`default_nettype wire

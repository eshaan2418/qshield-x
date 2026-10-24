// Abstract replacement for qsx_uf_core used for unbounded (k-induction) proofs of the shell.
// Same ports. Latency, status and results are unconstrained (anyseq) except for the guarantees the
// real core provides (checked separately on the real core, core_formal.sv):
//   * done is a one-cycle pulse after start; busy from start until done; outputs stable while idle;
//   * status != OK  ->  corr == 0 and obs == 0.
// The stub additionally ASSERTS that thr_in never changes while busy (no reconfiguration mid-decode).
`default_nettype none
`include "qsx_graph_defs.svh"
module qsx_uf_core #(parameter int LANES = 8, parameter int RB = 8, parameter int CB = 20) (
  input  wire clk, input wire rst_n, input wire start,
  input  wire [`QSX_V-1:0] defect_in,
  input  wire [`QSX_E*`QSX_TB-1:0] thr_in,
  input  wire [RB-1:0] max_rounds, input wire [CB-1:0] cycle_budget,
  output wire busy, output wire done,
  output reg [2:0] status, output wire obs, output wire [`QSX_E-1:0] corr,
  output reg [CB-1:0] cycles, output reg [RB-1:0] rounds
);
  localparam int E = `QSX_E;
  (* anyseq *) wire nd_fin;
  (* anyseq *) wire [2:0] nd_status;
  (* anyseq *) wire nd_obs;
  (* anyseq *) wire [E-1:0] nd_corr;
  reg [1:0] st;  // 0 idle, 1 busy, 2 done
  reg obs_r;
  reg [E-1:0] corr_r;
  reg [`QSX_E*`QSX_TB-1:0] thr_at_start;
  assign busy = (st != 2'd0);
  assign done = (st == 2'd2);
  assign obs = (status == 3'd0) & obs_r;
  assign corr = (status == 3'd0) ? corr_r : {E{1'b0}};
  always @(posedge clk) begin
    if (!rst_n) begin
      st <= 2'd0; status <= 3'd0; obs_r <= 1'b0; corr_r <= {E{1'b0}}; cycles <= 0; rounds <= 0;
    end else case (st)
      2'd0: if (start) begin st <= 2'd1; thr_at_start <= thr_in; end
      2'd1: if (nd_fin) begin
        st <= 2'd2;
        status <= (nd_status > 3'd3) ? 3'd0 : nd_status;
        obs_r <= nd_obs;
        corr_r <= nd_corr;
      end
      default: st <= 2'd0;
    endcase
  end
  always @(*) if (rst_n && st == 2'd1) assert (thr_in == thr_at_start);
  wire unused = &{1'b0, defect_in, max_rounds, cycle_budget, LANES[0]};
endmodule
`default_nettype wire

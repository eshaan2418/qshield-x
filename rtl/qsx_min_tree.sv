// Balanced binary min-reduction of N unsigned W-bit values (packed, element i at [i*W +: W]).
`default_nettype none
module qsx_min_tree #(
  parameter int N = 4,
  parameter int W = 8
) (
  input  wire [N*W-1:0] in,
  output wire [W-1:0]   out
);
  localparam int L = (N <= 1) ? 1 : (1 << $clog2(N));  // leaves (power of two)
  wire [W-1:0] t [0:2*L-2];
  genvar i;
  generate
    for (i = 0; i < L; i = i + 1) begin : g_leaf
      if (i < N) begin : g_in
        assign t[L-1+i] = in[i*W +: W];
      end else begin : g_pad
        assign t[L-1+i] = {W{1'b1}};
      end
    end
    for (i = 0; i < L-1; i = i + 1) begin : g_node
      assign t[i] = (t[2*i+1] < t[2*i+2]) ? t[2*i+1] : t[2*i+2];
    end
  endgenerate
  assign out = t[0];
endmodule
`default_nettype wire

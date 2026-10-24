// AXI-Stream ingress: frames of 1 header beat + W payload beats (tlast on the last) are written into
// a BRAM ring of NBUF frame slots. A frame becomes visible to the reader only once fully received
// ("commit"). tready is low while all slots are occupied, so a stored frame is never overwritten.
//   header: [31:24] = 8'hA5 magic, [15:0] = round tag
// Malformed frames (bad magic, early tlast, missing tlast) are committed with ferr=1 so that the
// response stream stays in order; surplus beats of an over-long frame are dropped until tlast.
`default_nettype none
module qsx_ingress #(
  parameter int W    = 1,   // payload beats per frame
  parameter int NBUF = 4    // frame slots (power of two)
) (
  input  wire        clk,
  input  wire        rst_n,
  input  wire [31:0] s_tdata,
  input  wire        s_tvalid,
  output wire        s_tready,
  input  wire        s_tlast,
  // reader side
  output wire        rd_avail,        // at least one committed frame
  output wire        rd_ferr,         // head frame is malformed
  input  wire [$clog2(W+1)-1:0] rd_beat,
  output reg  [31:0] rd_data,         // registered: data for rd_beat of the head frame, 1 cycle later
  input  wire        rd_pop,          // release head frame slot
  output wire [$clog2(NBUF):0] count
`ifdef FORMAL
  , output wire f_partial              // a frame has started but is not yet committed
  , output wire f_hdr_next             // next accepted beat is a frame header
  , output wire [NBUF*16-1:0] f_slot_tag  // header tag stored in each slot
  , output wire [((NBUF <= 1) ? 1 : $clog2(NBUF))-1:0] f_rslot
`endif
);
  localparam int BB = $clog2(W+1);          // beat index bits
  localparam int SW = 1 << BB;              // slot stride
  localparam int NB = (NBUF <= 1) ? 1 : $clog2(NBUF);

  (* ram_style = "block" *) reg [31:0] mem [0:NBUF*SW-1];
  reg [NB-1:0] wslot, rslot;
  reg [NB:0]   cnt;
  reg [BB-1:0] wbeat;
  reg          werr, drop;
  reg [NBUF-1:0] ferr;

  wire full = (cnt == NBUF[NB:0]);
  assign s_tready = drop || !full;
  wire acc = s_tvalid && s_tready;
  wire last_slot_beat = (wbeat == BB'(W));
  // commit when the frame ends (tlast) or reaches its nominal length (W beats after header)
  wire commit = acc && !drop && (s_tlast || last_slot_beat);
  wire bad_beat = (wbeat == {BB{1'b0}}) && (s_tdata[31:24] != 8'hA5);
  wire frame_err = werr || bad_beat || (s_tlast != last_slot_beat);
  wire pop = rd_pop && (cnt != {(NB+1){1'b0}});

  assign rd_avail = (cnt != {(NB+1){1'b0}});
  assign rd_ferr  = ferr[rslot];
  assign count    = cnt;

  always @(posedge clk) begin
    if (acc && !drop) mem[{wslot, wbeat}] <= s_tdata;
    rd_data <= mem[{rslot, rd_beat}];
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      wslot <= {NB{1'b0}};
      rslot <= {NB{1'b0}};
      cnt   <= {(NB+1){1'b0}};
      wbeat <= {BB{1'b0}};
      werr  <= 1'b0;
      drop  <= 1'b0;
      ferr  <= {NBUF{1'b0}};
    end else begin
      if (acc) begin
        if (drop) begin
          if (s_tlast) drop <= 1'b0;
        end else if (commit) begin
          ferr[wslot] <= frame_err;
          wslot <= wslot + 1'b1;
          wbeat <= {BB{1'b0}};
          werr  <= 1'b0;
          drop  <= !s_tlast;  // nominal length reached without tlast: drop the remainder
        end else begin
          wbeat <= wbeat + 1'b1;
          werr  <= werr || bad_beat;
        end
      end
      if (pop) rslot <= rslot + 1'b1;
      cnt <= cnt + {{NB{1'b0}}, commit} - {{NB{1'b0}}, pop};
    end
  end

`ifdef FORMAL
  assign f_partial = (wbeat != {BB{1'b0}}) && !drop;
  assign f_hdr_next = (wbeat == {BB{1'b0}}) && !drop;
  assign f_rslot = rslot;
  genvar fs;
  generate for (fs = 0; fs < NBUF; fs = fs + 1) begin : g_ftag
    assign f_slot_tag[fs*16 +: 16] = mem[fs*SW][15:0];
  end endgenerate
  // ---- properties (see formal/README.md); checked with SymbiYosys
  // Checked whenever reset is deasserted; the formal environment applies reset in cycle 0.
  always @(*) if (rst_n) assert (cnt <= NBUF[NB:0]);
  // No silent overwrite: while the ring is full, no beat is written to memory.
  always @(*) if (rst_n && full && !drop) assert (!acc);
  // Occupancy matches pointer distance.
  always @(*) if (rst_n) assert (cnt[NB-1:0] == NB'(wslot - rslot));
  always @(*) if (rst_n && cnt == {(NB+1){1'b0}}) assert (wslot == rslot);
  // Framing state: the beat counter is idle while dropping and never exceeds the frame length.
  always @(*) if (rst_n) assert (!drop || wbeat == {BB{1'b0}});
  always @(*) if (rst_n) assert (wbeat <= BB'(W));
`endif
endmodule
`default_nettype wire

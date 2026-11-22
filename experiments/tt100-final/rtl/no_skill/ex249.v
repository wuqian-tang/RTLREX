module top(input [15:0] x, output [7:0] y);
  // Two unsigned 7-bit fields; x[7] and x[15] are don't-cares.
  wire [6:0] a = x;
  wire [6:0] b = x[14:8];
  wire a_is_larger = a > b;
  wire [6:0] hi = a_is_larger ? a : b;
  wire [6:0] lo = a_is_larger ? b : a;
  wire [6:0] gap = hi-lo;
  wire [1:0] phase = hi[1:0];
  wire [7:0] doubled_gap = gap << 1;

  // The encoded sum is the larger field plus zero, one, or two
  // close-operand corrections.  correction2 is nested in correction1.
  wire correction1 = hi < 126 &&
    doubled_gap < 8 + phase &&
    lo >= 2 + (gap >= 2);
  // In seven-bit modular arithmetic this last test means 4 <= lo <= 124.
  wire correction2 = doubled_gap <= phase && (lo-7'd4) < 7'd121;

  assign y = hi + correction1 + correction2;
endmodule

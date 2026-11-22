module top(input [15:0] x, output [15:0] y);
  // Binary16 reciprocal-square.  The sign is ignored; subnormal results flush
  // to zero, overflow becomes infinity, and every input NaN is canonicalized.
  wire [14:0] a = x[14:0];
  wire [10:0] m = {1'b1, x[9:0]};
  wire [21:0] square = m * m;
  wire [1:0] adjust = (x[9:0] == 0) ? 2 : (x[9:0] <= 10'd424);
  wire [32:0] numerator = 33'd4294967296 >> adjust;
  // Adding half the divisor implements round-to-nearest (ties cannot occur
  // here because the numerator is a power of two).
  wire [32:0] significand = (numerator + (square >> 1)) / square;
  wire [5:0] exponent = 6'd43 - {x[14:10], 1'b0} + adjust;

  assign y = (a > 15'h7c00) ? 16'h7e00 :
             (a <= 15'h1c00) ? 16'h7c00 :
             (a > 15'h5800) ? 16'h0000 :
             {exponent[4:0], significand[9:0]};
endmodule

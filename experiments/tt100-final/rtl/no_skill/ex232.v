module top(input [15:0] x, output [15:0] y);
  // Binary16 magnitude square.  The table ignores the input sign, flushes
  // small results to zero, saturates overflow, and canonicalizes NaNs.
  wire [14:0] magnitude = x;
  wire [4:0] exponent = magnitude[14:10];
  wire [9:0] fraction = magnitude;
  wire [10:0] significand = 1024 + fraction;
  wire [21:0] square = significand * significand;

  // Normalize to a fixed binary point.  For squared 11-bit significands,
  // halfway cases have an even retained bit, so this is round-to-nearest-even.
  wire normalize = square < 2097152;
  wire [21:0] normalized = square << normalize;
  wire [11:0] rounded = (normalized + 1023) >> 11;

  assign y = magnitude < 8192 ? 16'h0000 :
             magnitude > 31744 ? 16'h7e00 :
             magnitude >= 23552 ? 16'h7c00 :
             (exponent * 2 - 15 - normalize) * 1024 + rounded;
endmodule

// BF16 1/x^3, DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Reciprocal power: normalized integer significand power and exact RNE quotient.
module top(input [15:0] x, output [15:0] y);
  wire sign_in = x[15];
  wire [7:0] exponent = x[14:7];
  wire [6:0] fraction = x;
  wire [7:0] significand = 8'd128 + fraction;
  wire [23:0] denominator = significand ** 3;
  wire [1:0] normalize = denominator <= 24'd4194304 ? 2'd1 : denominator <= 24'd8388608 ? 2'd2 : 2'd3;
  wire [8:0] rounded = ((33'd268435456 << normalize) +
      (denominator >> 1)) / denominator;
  wire signed [10:0] result_exponent = 11'd508 - exponent * 11'd3 -
      normalize + rounded[8];
  wire special = exponent == 8'd255;
  wire [14:0] magnitude = result_exponent <= 0 ? 15'd0 :
      result_exponent >= 11'd255 ? 15'h7f80 :
      result_exponent * 15'd128 + rounded[6:0];
  assign y = special && fraction ? 16'h7fc0 : {sign_in, magnitude};
endmodule

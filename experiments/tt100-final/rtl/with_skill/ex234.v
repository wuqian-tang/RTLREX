// FP16 1/x^2, DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Reciprocal power: normalized integer significand power and exact RNE quotient.
module top(input [15:0] x, output [15:0] y);
  wire [4:0] exponent = x[14:10];
  wire [9:0] fraction = x;
  wire [10:0] significand = 11'd1024 + fraction;
  wire [21:0] denominator = significand ** 2;
  wire [1:0] normalize = denominator <= 22'd2097152 ? 2'd1 : 2'd2;
  wire [11:0] rounded = ((34'd1073741824 << normalize) +
      (denominator >> 1)) / denominator;
  wire signed [7:0] result_exponent = 8'd45 - exponent * 8'd2 -
      normalize + rounded[11];
  wire special = exponent == 5'd31;
  wire [14:0] magnitude = exponent == 0 ? 15'h7c00 :
      (special || result_exponent <= 0) ? 15'd0 :
      result_exponent >= 8'd31 ? 15'h7c00 :
      result_exponent * 15'd1024 + rounded[9:0];
  assign y = special && fraction ? 16'h7e00 : magnitude;
endmodule

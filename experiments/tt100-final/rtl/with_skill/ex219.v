// BF16 1/cbrt(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Exact reciprocal cube root from numeric output candidates and midpoint powers.
module top(input [15:0] x, output reg [15:0] y);
  wire [14:0] absolute_input = x[14:0];
  wire [7:0] exponent = x[14:7];
  wire [1:0] remainder = (exponent + 10'd2) % 3;
  wire [9:0] exponent_before_hidden = (10'd504 - exponent) / 3;
  reg [7:0] significand;
  reg [8:0] midpoint;
  reg [8:0] root;
  reg [35:0] target;
  reg [35:0] powered_midpoint;
  reg [14:0] magnitude;
  always @(*) begin
    significand = x;
    significand[7] = 1'b1;
    target = 36'd17179869184 >> remainder;
    root = 9'd128;
    midpoint = 9'd257;
    repeat (128) begin
      powered_midpoint = midpoint ** 3 * significand;
      root = root + (powered_midpoint < target);
      midpoint = midpoint + 2;
    end
    magnitude = exponent_before_hidden * 15'd128 + root;
    if (exponent == 0) magnitude = 15'h7f80;
    else if (absolute_input == 15'h7f80) magnitude = 0;
    y = x;
    y[14:0] = magnitude;
    if (absolute_input > 15'h7f80) y = 16'h7fc0;
  end
endmodule

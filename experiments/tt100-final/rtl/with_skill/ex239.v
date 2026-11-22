// FP16 1/cbrt(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Exact reciprocal cube root from numeric output candidates and midpoint powers.
module top(input [15:0] x, output [15:0] y);
  wire [14:0] absolute_input = x[14:0];
  wire [4:0] exponent = x[14:10];
  wire [1:0] remainder = exponent % 3;
  wire [6:0] exponent_before_hidden = (7'd56 - exponent) / 3;
  reg [10:0] significand;
  reg [11:0] midpoint;
  reg [11:0] root;
  reg [47:0] target;
  reg [47:0] powered_midpoint;
  reg [14:0] magnitude;
  always @(*) begin
    significand = x;
    significand[10] = 1'b1;
    target = 48'd70368744177664 >> remainder;
    root = 12'd1024;
    midpoint = 12'd2049;
    repeat (1024) begin
      powered_midpoint = midpoint ** 3 * significand;
      root = root + (powered_midpoint < target);
      midpoint = midpoint + 2;
    end
    magnitude = exponent_before_hidden * 15'd1024 + root;
    if (exponent == 0) magnitude = 15'h7c00;
    else if (absolute_input == 15'h7c00) magnitude = 0;
  end
  assign y = absolute_input > 15'h7c00 ? 16'h7e00 : {x[15], magnitude};
endmodule

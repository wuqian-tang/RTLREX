// BF16 sqrt(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Exact nearest-integer square-root Newton recurrence, bounded by fraction width.
module top(input [15:0] x, output reg [15:0] y);
  wire [7:0] exponent = x[14:7];
  wire [8:0] exponent_before_hidden = (exponent + 9'd125) >> 1;
  reg [7:0] significand;
  reg [15:0] radicand_minus_one;
  reg [8:0] root;
  always @(*) begin
    significand = x;
    significand[7] = 1'b1;
    radicand_minus_one = significand * (exponent[0] ? 16'd128 : 16'd256) - 1;
    root = 9'd256;
    repeat (8) root = (root + radicand_minus_one / root + 1) >> 1;
    if (exponent == 0) y = {x[15], 15'd0};
    else if (x > 16'h7f80) y = 16'h7fc0;
    else if (x == 16'h7f80) y = 16'h7f80;
    else y = exponent_before_hidden * 16'd128 + root;
  end
endmodule

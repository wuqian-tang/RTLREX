// FP16 sqrt(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Exact nearest-integer square-root Newton recurrence, bounded by fraction width.
module top(input [15:0] x, output reg [15:0] y);
  wire [4:0] exponent = x[14:10];
  wire [5:0] exponent_before_hidden = (exponent + 6'd13) >> 1;
  reg [10:0] significand;
  reg [21:0] radicand_minus_one;
  reg [11:0] root;
  always @(*) begin
    significand = x;
    significand[10] = 1'b1;
    radicand_minus_one = significand * (exponent[0] ? 22'd1024 : 22'd2048) - 1;
    root = 12'd2048;
    repeat (11) root = (root + radicand_minus_one / root + 1) >> 1;
    if (exponent == 0) y = {x[15], 15'd0};
    else if (x > 16'h7c00) y = 16'h7e00;
    else if (x == 16'h7c00) y = 16'h7c00;
    else y = exponent_before_hidden * 16'd1024 + root;
  end
endmodule

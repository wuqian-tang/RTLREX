// BF16 1/sqrt(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Rational midpoint-preserving integer bias and bounded nearest-root Newton.
module top(input [15:0] x, output reg [15:0] y);
  wire [14:0] input_magnitude = x;
  wire [7:0] exponent = x[14:7];
  wire [8:0] exponent_before_hidden = (9'd378 - exponent) >> 1;
  function greater;
    input [15:0] left, right;
    begin greater = left > right; end
  endfunction
  reg [7:0] significand;
  reg [15:0] biased_radicand;
  reg [8:0] root;
  always @(*) begin
    significand = x;
    significand[7] = 1'b1;
    biased_radicand = ((26'd16777216 << exponent[0]) - significand) / (significand << 2);
    root = 9'd256;
    repeat (8) root = (root + biased_radicand / root + 1) >> 1;
    if (greater(16'd128, input_magnitude)) begin
      y = x;
      y[14:0] = 15'd32640;
    end else if (greater(x, 16'd32639))
      y = greater(x, 16'd32640) ? 16'd32704 : 16'd0;
    else y = exponent_before_hidden * 16'd128 + root;
  end
endmodule

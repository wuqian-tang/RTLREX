// FP16 1/sqrt(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Rational midpoint-preserving integer bias and bounded nearest-root Newton.
module top(input [15:0] x, output reg [15:0] y);
  wire [14:0] input_magnitude = x;
  wire [4:0] exponent = x[14:10];
  wire [5:0] exponent_before_hidden = (6'd42 - exponent) >> 1;
  function greater;
    input [15:0] left, right;
    begin greater = left > right; end
  endfunction
  reg [10:0] significand;
  reg [21:0] biased_radicand;
  reg [11:0] root;
  always @(*) begin
    significand = x;
    significand[10] = 1'b1;
    biased_radicand = ((35'd8589934592 << exponent[0]) - significand) / (significand << 2);
    root = 12'd2048;
    repeat (11) root = (root + biased_radicand / root + 1) >> 1;
    if (greater(16'd1024, input_magnitude))
      y = {x[15], 15'd31744};
    else if (greater(x, 16'd31743))
      y = greater(x, 16'd31744) ? 16'd32256 : 16'd0;
    else y = exponent_before_hidden * 16'd1024 + root;
  end
endmodule

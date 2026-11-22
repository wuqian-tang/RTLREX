// FP8 E5M2 hypot, exact squared-midpoint RNE, canonical NaN
// Exact finite-only hypot: bounded adjacent numeric midpoints, no lookup table.
module top(input [15:0] x, output reg [7:0] y);
  wire [6:0] a = x[14:8], b = x;
  function [67:0] midpoint_squared;
    input [6:0] encoding;
    input half_step;
    reg [4:0] exponent;
    reg [1:0] fraction;
    reg normal;
    reg [33:0] decoded;
    begin
      exponent = encoding[6:2];
      fraction = encoding;
      normal = exponent != 0;
      decoded = {normal, fraction, half_step} << (exponent - normal);
      midpoint_squared = decoded * decoded;
    end
  endfunction
  function greater;
    input [68:0] left, right;
    begin greater = left > right; end
  endfunction
  wire [68:0] four_value = midpoint_squared(a, 1'b0) + midpoint_squared(b, 1'b0);
  reg [6:0] code;
  always @(*) begin
    code = greater(a, b) ? a : b;
    repeat (3) begin
      code = code + (greater(7'd126, code) &&
                     greater(four_value, midpoint_squared(code, 1'b1)));
    end
    y = code;
  end
endmodule

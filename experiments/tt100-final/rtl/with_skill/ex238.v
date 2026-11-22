// FP16 1/x^3, DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Normalized integer reciprocal power, exact RNE division and linear packing.
module top(input [15:0] x, output [15:0] y);
  wire sign_in = x[15];
  wire [14:0] input_magnitude = x;
  wire [4:0] exponent = input_magnitude[14:10];
  wire [9:0] fraction = input_magnitude;
  wire [10:0] significand = 11'd1024 + fraction;
  wire [32:0] denominator = significand ** 3;
  function signed [44:0] select_if_greater;
    input signed [44:0] left, right, when_true, when_false;
    begin select_if_greater = left > right ? when_true : when_false; end
  endfunction
  wire [1:0] normalize = select_if_greater(
      denominator, 45'sd4294967296, 2'd3,
      select_if_greater(denominator, 45'sd2147483648, 2'd2, 2'd1));
  wire [11:0] rounded = ((45'd1099511627776 << normalize) +
                            (denominator >> 1)) / denominator;
  wire signed [18:0] packed_result =
      (19'sd59 - exponent * 19'sd3 - normalize) *
      19'sd1024 + rounded;
  wire [14:0] magnitude = select_if_greater(
      45'sd31744, packed_result,
      select_if_greater(45'sd1024, packed_result, 15'd0, packed_result),
      15'd31744);
  assign y = select_if_greater(input_magnitude, 45'sd31744,
                               16'd32256, {sign_in, magnitude});
endmodule

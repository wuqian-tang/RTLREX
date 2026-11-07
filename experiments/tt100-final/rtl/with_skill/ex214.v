// BF16 1/x^2, DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Normalized integer reciprocal power, exact RNE division and linear packing.
module top(input [15:0] x, output [15:0] y);
  wire [14:0] input_magnitude = x;
  wire [7:0] exponent = input_magnitude[14:7];
  wire [6:0] fraction = input_magnitude;
  wire [7:0] significand = 8'd128 + fraction;
  wire [15:0] denominator = significand ** 2;
  function greater;
    input signed [18:0] left, right;
    begin greater = left > right; end
  endfunction
  wire [1:0] normalize = greater(denominator, 19'sd32768) ? 2'd2 : 2'd1;
  wire [8:0] rounded = ((25'd2097152 << normalize) +
                            (denominator >> 1)) / denominator;
  wire signed [18:0] packed_result =
      (19'sd380 - exponent * 19'sd2 - normalize) *
      19'sd128 + rounded;
  wire [14:0] magnitude = greater(19'sd32640, packed_result) ?
      (greater(19'sd128, packed_result) ? 15'd0 : packed_result) :
      15'd32640;
  assign y = greater(input_magnitude, 19'sd32640) ? 16'd32704 : magnitude;
endmodule

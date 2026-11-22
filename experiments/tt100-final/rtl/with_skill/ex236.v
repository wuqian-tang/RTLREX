// FP16 x^3, DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Format-wide proofs permit direct exact-cube rounding and carry-free packing.
module top(input [15:0] x, output reg [15:0] y);
  wire sign_in = x[15];
  wire [4:0] exponent = x[14:10];
  wire [9:0] fraction = x;
  wire [14:0] input_magnitude = x;
  wire [10:0] significand = 11'd1024 + fraction;
  wire [32:0] product = significand ** 3;
  wire [1:0] normalize = product[32] ? 2'd2 : product[31];
  wire signed [2:0] positive_normalize = normalize;
  wire [7:0] rounding_shift = 20 + normalize;
  wire [10:0] rounded = (product + (34'd524288 << normalize) - 1 + product[rounding_shift]) >> rounding_shift;
  wire [9:0] rounded_fraction = rounded;
  wire signed [7:0] positive_exponent = exponent;
  wire signed [7:0] output_exponent = 3 * positive_exponent - 30 + positive_normalize;
  wire signed [17:0] code = {output_exponent, rounded_fraction};
  reg [14:0] magnitude;
  always @(*) begin
    if (code >= 31744) magnitude = 15'd31744;
    else if (code < 1024) magnitude = code == 1023 ? 15'd1024 : 0;
    else magnitude = code;
    y = {sign_in, magnitude};
    if (input_magnitude > 31744) y = 16'd32256;
  end
endmodule

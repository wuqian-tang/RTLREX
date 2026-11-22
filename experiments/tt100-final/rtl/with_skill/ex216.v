// BF16 x^3, DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
module top(input [15:0] x, output reg [15:0] y);
  wire sign_in = x[15];
  wire [7:0] exponent = x[14:7];
  wire [6:0] fraction = x;
  wire [14:0] input_magnitude = x;
  wire [7:0] significand = 8'd128 + fraction;
  wire [23:0] product = significand ** 3;
  wire [1:0] normalize = product[23] ? 2'd2 : product[22];
  wire signed [2:0] positive_normalize = normalize;
  wire [7:0] rounded = ((product >> normalize) + 25'd8192) >> 14;
  wire [6:0] rounded_fraction = rounded;
  wire signed [10:0] positive_exponent = exponent;
  wire signed [10:0] output_exponent = 3 * positive_exponent - 254 + positive_normalize;
  reg [14:0] magnitude;
  always @(*) begin
    magnitude = rounded_fraction;
    magnitude[14:7] = output_exponent;
    if (output_exponent >= 255) magnitude = 15'd32640;
    else if (output_exponent < 1) magnitude = 0;
    y = magnitude;
    y[15] = sign_in;
    if (input_magnitude > 32640) y = 16'd32704;
  end
endmodule

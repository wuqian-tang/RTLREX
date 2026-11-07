// BF16 1/x, DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
module top(input [15:0] x, output [15:0] y);
  wire sign_in = x[15];
  wire [7:0] exponent = x[14:7];
  wire [6:0] fraction = x;
  wire [7:0] denominator = 8'd128 + fraction;
  wire [8:0] rounded = (17'd32768 + (denominator >> 1)) / denominator;
  wire signed [16:0] packed = (17'sd252 - exponent) * 17'sd128 + rounded;
  wire special = exponent == 8'd255;
  wire [14:0] magnitude = exponent == 0 ? 15'h7f80 :
      packed < 17'sd128 ? 15'd0 : packed;
  assign y = special && fraction ? 16'h7fc0 : {sign_in, magnitude};
endmodule

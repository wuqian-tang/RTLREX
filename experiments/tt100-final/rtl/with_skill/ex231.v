// FP16 1/x, DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
module top(input [15:0] x, output [15:0] y);
  wire sign_in = x[15];
  wire [4:0] exponent = x[14:10];
  wire [9:0] fraction = x;
  wire [10:0] denominator = 11'd1024 + fraction;
  wire [11:0] rounded = (23'd2097152 + (denominator >> 1)) / denominator;
  wire signed [16:0] packed_word = 17'd28672 - exponent * 17'd1024 + rounded;
  wire special = exponent == 5'd31;
  wire [14:0] magnitude = exponent == 0 ? 15'h7c00 :
      (special || packed_word < 17'sd1024) ? 15'd0 : packed_word;
  assign y = special && fraction ? 16'h7e00 : {sign_in, magnitude};
endmodule

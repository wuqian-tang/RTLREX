module top(in1, in2, in3, in4, in5, in6, out1, out2, out3, out4, out5);
  input [1:0] in1, in2;
  input [4:0] in3, in5;
  input [2:0] in4, in6;
  output [4:0] out1, out3, out5;
  output out2, out4;

  wire [2:0] wide_in1, offset;
  wire [4:0] word_in2, word_in4, word_in6, word_offset;
  wire signed [4:0] signed_out1, signed_out3, signed_in3, signed_in5;
  assign wide_in1 = in1;
  assign offset = 3'd1 - wide_in1;
  assign word_in2 = in2;
  assign word_in4 = in4;
  assign word_in6 = in6;
  assign word_offset = offset;

  assign out1 = word_in2 + word_offset;
  assign out3 = word_in4 + word_offset;
  assign out5 = word_in6 + word_offset;
  assign signed_out1 = out1;
  assign signed_out3 = out3;
  assign signed_in3 = in3;
  assign signed_in5 = in5;
  assign out2 = signed_out1 < signed_in3;
  assign out4 = signed_out3 < signed_in5;
endmodule

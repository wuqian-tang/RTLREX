module top(in1, in2, in3, out1, out2, out3, out4, out5, out6);
  input [30:0] in1;
  input [31:0] in2, in3;
  output [32:0] out1, out4;
  output out2, out3, out5, out6;

  wire [32:0] wide_in1, wide_in2, wide_in3, base;
  wire signed [32:0] signed_out1, signed_out4;
  assign wide_in1 = in1;
  assign wide_in2 = in2;
  assign wide_in3 = in3;
  assign base = 33'h1fffffffe - wide_in1;
  assign out1 = base + wide_in2;
  assign out4 = base + wide_in3;
  assign signed_out1 = out1;
  assign signed_out4 = out4;

  assign out2 = signed_out1 > 33'sd7;
  assign out3 = signed_out1 < 33'sh1fffffffc;
  assign out5 = signed_out4 > 33'sd7;
  assign out6 = signed_out4 < 33'sh1fffffffc;
endmodule

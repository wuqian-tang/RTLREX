module top(in1, in2, in3, out1, out2);
  input [15:0] in1, in2, in3;
  output [31:0] out1, out2;
  assign out1 = in1 * in2 + in3 + 1;
  assign out2 = out1 - 2;
endmodule

module top(in1, in2, in3, out1, out2);
  input [7:0] in1, in2, in3;
  output [23:0] out1;
  output [15:0] out2;
  wire [15:0] square;
  assign square = in1 * in1;
  assign out1 = square * in1;
  assign out2 = in1 * in3;
endmodule

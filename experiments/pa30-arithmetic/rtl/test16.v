module top(in1, in2, in3, in4, out1, out2, out3, out4);
  input [33:0] in1;
  input [34:0] in2, in3, in4;
  output out1, out2, out3, out4;

  wire signed [34:0] signed_in2, signed_in3, signed_in4;
  wire signed [35:0] base, rhs2, rhs3, rhs4, threshold;
  assign signed_in2 = in2;
  assign signed_in3 = in3;
  assign signed_in4 = in4;
  assign base = in1;
  assign rhs2 = signed_in2;
  assign rhs3 = signed_in3;
  assign rhs4 = signed_in4;
  assign threshold = base - 1;

  assign out1 = threshold >= rhs2;
  assign out2 = threshold == rhs3;
  assign out3 = threshold == rhs4;
  assign out4 = threshold > rhs4;
endmodule

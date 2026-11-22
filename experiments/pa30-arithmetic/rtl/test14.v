module top(in1, in2, in3, out1);
  input [2:0] in1;
  input [3:0] in2;
  input [8:0] in3;
  output out1;

  wire signed [8:0] lhs, rhs, comparison_value, difference;
  assign lhs = in1;
  assign rhs = in2;
  assign comparison_value = in3;
  assign difference = lhs - rhs;
  assign out1 = comparison_value < difference;
endmodule

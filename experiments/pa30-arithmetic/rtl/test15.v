module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, out1, out2, out3);
  input [12:0] in1;
  input [17:0] in2;
  input [31:0] in3, in7, in9;
  input in4, in5, in6, in8;
  input [4:0] in10;
  input [15:0] in11;
  output [32:0] out1;
  output [31:0] out2, out3;

  wire [32:0] wide_in1, wide_in2, wide_in3;
  wire [31:0] word_in1, word_in10, secondary_product, selected;
  assign wide_in1 = in1;
  assign wide_in2 = in2;
  assign wide_in3 = in3;
  assign word_in1 = in1;
  assign word_in10 = in10;

  assign out1 = wide_in3 + wide_in1 * wide_in2;
  assign out2 = out1 + 33'd64;
  assign secondary_product = word_in1 * word_in10;
  assign selected = in4 ? out2
                        : (in5 ? out1
                               : (in6 ? in9 + secondary_product : in7));
  assign out3 = selected + in11;
endmodule

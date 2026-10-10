module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, in16, in17, in18, in19, in20, in21, in22, in23, in24, in25, in26, in27, in28, in29, in30, in31, out1);
  input [6:0] in1, in2, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, in16, in17, in18, in19, in20, in21, in22, in23, in24, in25, in26, in27, in28, in29, in30, in31;
  input in3, in4;
  output [12:0] out1;

  wire [12:0] x1, x2, x5, x6, x7, x8, x9, x10, x11, x12, x13;
  wire [12:0] x14, x15, x16, x17, x18, x19, x20, x21, x22, x23;
  wire [12:0] x24, x25, x26, x27, x28, x29, x30, x31;
  wire [12:0] sum_twos, sum_fours, group_zero, group_one, selected;
  assign x1 = in1;
  assign x2 = in2;
  assign x5 = in5;
  assign x6 = in6;
  assign x7 = in7;
  assign x8 = in8;
  assign x9 = in9;
  assign x10 = in10;
  assign x11 = in11;
  assign x12 = in12;
  assign x13 = in13;
  assign x14 = in14;
  assign x15 = in15;
  assign x16 = in16;
  assign x17 = in17;
  assign x18 = in18;
  assign x19 = in19;
  assign x20 = in20;
  assign x21 = in21;
  assign x22 = in22;
  assign x23 = in23;
  assign x24 = in24;
  assign x25 = in25;
  assign x26 = in26;
  assign x27 = in27;
  assign x28 = in28;
  assign x29 = in29;
  assign x30 = in30;
  assign x31 = in31;

  assign sum_twos = x7 + x8 + x9 + x10 + x11 + x12
                  + x13 + x14 + x15 + x16 + x17 + x18;
  assign sum_fours = x23 + x24 + x25 + x26 + x27
                   + x28 + x29 + x30 + x31;
  assign group_zero = x5 + x6 + x21 + x22;
  assign group_one = x1 + x2 + x19 + x20;
  assign selected = in3 ? group_one : group_zero;
  assign out1 = 13'd32 + (sum_twos << 1) + (sum_fours << 2) + selected;
endmodule

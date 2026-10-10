module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, out1, out2, out3, out4, out5);
  input [11:0] in1, in2, in7;
  input in3, in4, in5, in6, in8, in9, in10, in11, in12, in13, in14, in15;
  output out1, out2, out3, out4, out5;

  wire signed [11:0] s1, s2, s7;
  wire signed [12:0] sum, twice;
  wire p12, p17_lt, p17_gt, p27, mid_lt, mid_gt;
  assign s1 = in1;
  assign s2 = in2;
  assign s7 = in7;
  assign sum = s1 + s7;
  assign twice = s2 + s2;

  assign p12 = s1 < s2;
  assign p17_lt = s1 < s7;
  assign p17_gt = s1 > s7;
  assign p27 = s2 < s7;
  assign mid_lt = twice < sum;
  assign mid_gt = twice > sum;

  assign out1 = in3 ? (in5 ? mid_lt : p17_gt)
                    : (in5 ? p17_lt : mid_gt);
  assign out2 = in8 ? (in10 ? mid_lt : p17_lt)
                    : (in10 ? p17_gt : mid_gt);
  assign out3 = in12 ? (in14 ? mid_lt : p17_lt)
                     : (in14 ? p17_gt : mid_gt);
  assign out4 = p27;
  assign out5 = p12;
endmodule

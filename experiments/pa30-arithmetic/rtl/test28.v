module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, out1, out2, out3, out4, out5, out6);
  input [10:0] in1, in2, in3, in4, in5, in6;
  input [10:0] in7, in8, in9, in10, in11, in12;
  output out1, out2, out3, out4, out5, out6;

  wire [21:0] sq1_n, sq2_n, sq3_n, sq4_n, sq5_n, sq6_n;
  wire [21:0] sq7_n, sq8_n, sq9_n, sq10_n, sq11_n, sq12_n;
  wire [23:0] sq1, sq2, sq3, sq4, sq5, sq6;
  wire [23:0] sq7, sq8, sq9, sq10, sq11, sq12;
  wire [23:0] pair23, pair67, pair1011;
  wire [23:0] sum123, sum234, sum567;
  wire [23:0] sum678, sum91011, sum101112;

  assign sq1_n = in1 * in1;
  assign sq2_n = in2 * in2;
  assign sq3_n = in3 * in3;
  assign sq4_n = in4 * in4;
  assign sq5_n = in5 * in5;
  assign sq6_n = in6 * in6;
  assign sq7_n = in7 * in7;
  assign sq8_n = in8 * in8;
  assign sq9_n = in9 * in9;
  assign sq10_n = in10 * in10;
  assign sq11_n = in11 * in11;
  assign sq12_n = in12 * in12;

  assign sq1 = sq1_n;
  assign sq2 = sq2_n;
  assign sq3 = sq3_n;
  assign sq4 = sq4_n;
  assign sq5 = sq5_n;
  assign sq6 = sq6_n;
  assign sq7 = sq7_n;
  assign sq8 = sq8_n;
  assign sq9 = sq9_n;
  assign sq10 = sq10_n;
  assign sq11 = sq11_n;
  assign sq12 = sq12_n;

  assign pair23 = sq2 + sq3;
  assign pair67 = sq6 + sq7;
  assign pair1011 = sq10 + sq11;
  assign sum123 = sq1 + pair23;
  assign sum234 = pair23 + sq4;
  assign sum567 = sq5 + pair67;
  assign sum678 = pair67 + sq8;
  assign sum91011 = sq9 + pair1011;
  assign sum101112 = pair1011 + sq12;

  assign out1 = sum234 < sum567;
  assign out2 = sum123 < sum678;
  assign out3 = sum678 > sum91011;
  assign out4 = sum101112 > sum234;
  assign out5 = sum101112 < sum567;
  assign out6 = sum123 < sum91011;
endmodule

module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, in16, in17, in18, in19, in20, in21, in22, in23, in24, in25, in26, out1);
  input [31:0] in1, in2, in3, in4, in5, in7, in9, in10, in11, in12, in13;
  input [31:0] in14, in15, in16, in17, in18, in19, in20, in21, in22, in23, in24, in25, in26;
  input [30:0] in6, in8;
  output [68:0] out1;

  wire signed [31:0] s_in1, s_in2, s_in3, s_in4, s_in9, s_in10, s_in11;
  wire signed [31:0] s_in12, s_in13, s_in14, s_in15, s_in16, s_in17;
  wire signed [31:0] s_in18, s_in19, s_in20, s_in21, s_in22, s_in23;
  wire signed [31:0] s_in24, s_in25, s_in26;
  wire signed [63:0] product_0, product_1, product_4, product_5, product_6;
  wire signed [63:0] product_7, product_8, product_9, product_10, product_11, product_12;
  wire [62:0] product_2, product_3;
  wire [68:0] term_0, term_1, term_2, term_3, term_4, term_5, term_6;
  wire [68:0] term_7, term_8, term_9, term_10, term_11, term_12;

  assign s_in1 = in1;
  assign s_in2 = in2;
  assign s_in3 = in3;
  assign s_in4 = in4;
  assign s_in9 = in9;
  assign s_in10 = in10;
  assign s_in11 = in11;
  assign s_in12 = in12;
  assign s_in13 = in13;
  assign s_in14 = in14;
  assign s_in15 = in15;
  assign s_in16 = in16;
  assign s_in17 = in17;
  assign s_in18 = in18;
  assign s_in19 = in19;
  assign s_in20 = in20;
  assign s_in21 = in21;
  assign s_in22 = in22;
  assign s_in23 = in23;
  assign s_in24 = in24;
  assign s_in25 = in25;
  assign s_in26 = in26;

  assign product_0 = s_in1 * s_in2;
  assign product_1 = s_in3 * s_in4;
  assign product_2 = in5 * in6;
  assign product_3 = in7 * in8;
  assign product_4 = s_in9 * s_in10;
  assign product_5 = s_in11 * s_in12;
  assign product_6 = s_in13 * s_in14;
  assign product_7 = s_in15 * s_in16;
  assign product_8 = s_in17 * s_in18;
  assign product_9 = s_in19 * s_in20;
  assign product_10 = s_in21 * s_in22;
  assign product_11 = s_in23 * s_in24;
  assign product_12 = s_in25 * s_in26;

  assign term_0 = product_0;
  assign term_1 = product_1;
  assign term_2 = product_2;
  assign term_3 = product_3;
  assign term_4 = product_4;
  assign term_5 = product_5;
  assign term_6 = product_6;
  assign term_7 = product_7;
  assign term_8 = product_8;
  assign term_9 = product_9;
  assign term_10 = product_10;
  assign term_11 = product_11;
  assign term_12 = product_12;

  assign out1 = term_0 + term_1 + term_2 + term_3 + term_4 + term_5
              + term_6 + term_7 + term_8 + term_9 + term_10 + term_11
              + term_12;
endmodule

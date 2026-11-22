module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, in16, in17, in18, in19, in20, in21, in22, in23, in24, in25, in26, in27, in28, in29, in30, in31, in32, in33, out1, out2);
  input [6:0] in1, in2;
  input [15:0] in3, in9, in31;
  input [14:0] in4;
  input in5, in6, in28, in29;
  input [8:0] in7, in12, in16, in20, in24;
  input [12:0] in8, in13, in17, in21, in25;
  input [4:0] in10, in11, in14, in15, in18, in19, in22, in23, in26, in27;
  input [11:0] in30;
  input [3:0] in32, in33;
  output [15:0] out1, out2;

  wire signed [6:0] s1, s2;
  wire signed [15:0] s3, s9, s31;
  wire signed [14:0] s4;
  wire signed [12:0] s8, s13, s17, s21, s25;
  wire signed [4:0] s10, s11, s14, s15, s18, s19, s22, s23, s26, s27;
  assign s1 = in1;   assign s2 = in2;   assign s3 = in3;   assign s4 = in4;
  assign s8 = in8;   assign s9 = in9;   assign s10 = in10; assign s11 = in11;
  assign s13 = in13; assign s14 = in14; assign s15 = in15;
  assign s17 = in17; assign s18 = in18; assign s19 = in19;
  assign s21 = in21; assign s22 = in22; assign s23 = in23;
  assign s25 = in25; assign s26 = in26; assign s27 = in27; assign s31 = in31;

  wire signed [7:0] diff0;
  wire signed [23:0] product0, shifted0;
  wire signed [15:0] base0;
  assign diff0 = s1 - s2;
  assign product0 = diff0 * s3;
  assign shifted0 = product0 >>> 7;
  assign base0 = s4;
  assign out1 = base0 + shifted0;

  wire signed [5:0] diff1, diff2, diff3, diff4, diff5;
  wire signed [21:0] product1, product2, product3, product4, product5;
  wire signed [21:0] shifted1, shifted2, shifted3, shifted4, shifted5;
  wire signed [15:0] base1, base2, base3, base4, base5;
  wire [15:0] inner1, inner2, inner3, inner4, inner5;

  assign diff1 = s10 - s11;
  assign product1 = diff1 * s9;
  assign shifted1 = product1 >>> 7;
  assign base1 = s8;
  assign inner1 = base1 + shifted1;

  assign diff2 = s14 - s15;
  assign product2 = diff2 * s9;
  assign shifted2 = product2 >>> 7;
  assign base2 = s13;
  assign inner2 = base2 + shifted2;

  assign diff3 = s18 - s19;
  assign product3 = diff3 * s9;
  assign shifted3 = product3 >>> 7;
  assign base3 = s17;
  assign inner3 = base3 + shifted3;

  assign diff4 = s22 - s23;
  assign product4 = diff4 * s9;
  assign shifted4 = product4 >>> 7;
  assign base4 = s21;
  assign inner4 = base4 + shifted4;

  assign diff5 = s26 - s27;
  assign product5 = diff5 * s9;
  assign shifted5 = product5 >>> 7;
  assign base5 = s25;
  assign inner5 = base5 + shifted5;

  wire [24:0] outer_product1, outer_product2, outer_product3;
  wire [24:0] outer_product4, outer_product5;
  wire [15:0] term1, term2, term3, term4, term5, five_term_sum;
  assign outer_product1 = in7 * inner1;
  assign outer_product2 = in12 * inner2;
  assign outer_product3 = in16 * inner3;
  assign outer_product4 = in20 * inner4;
  assign outer_product5 = in24 * inner5;
  assign term1 = outer_product1 >> 8;
  assign term2 = outer_product2 >> 8;
  assign term3 = outer_product3 >> 8;
  assign term4 = outer_product4 >> 8;
  assign term5 = outer_product5 >> 8;
  assign five_term_sum = term1 + term2 + term3 + term4 + term5;

  wire signed [4:0] u32, u33, diff6;
  wire signed [20:0] product6, shifted6;
  wire [14:0] truncated6;
  wire [15:0] final_term;
  assign u32 = in32;
  assign u33 = in33;
  assign diff6 = u32 - u33;
  assign product6 = diff6 * s31;
  assign shifted6 = product6 >>> 7;
  assign truncated6 = shifted6;
  assign final_term = in30 + truncated6;

  assign out2 = out1
              + (in5 ? five_term_sum : 16'd0)
              + (in28 ? final_term : 16'd0);
endmodule

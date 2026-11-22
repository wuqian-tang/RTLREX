module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, in16, in17, in18, in19, in20, in21, in22, in23, in24, in25, in26, in27, in28, in29, in30, in31, in32, in33, in34, in35, in36, in37, in38, in39, in40, in41, in42, in43, in44, in45, in46, in47, in48, in49, in50, in51, in52, in53, in54, in55, in56, in57, in58, in59, in60, in61, in62, out1, out2);
  input [15:0] in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11;
  input [15:0] in12, in13, in14, in15, in16, in17, in18, in19, in20, in21;
  input [15:0] in22, in23, in24, in25, in26, in27, in28, in29, in30, in31;
  input [15:0] in32, in33, in34, in35, in36, in37, in38, in39, in40, in41;
  input [15:0] in42, in43, in44, in45, in46, in47, in48, in49, in50, in51;
  input [15:0] in52, in53, in54, in55, in56, in57, in58, in59, in60, in61;
  input in62;
  output [28:0] out1;
  output [16:0] out2;

  wire signed [15:0] s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12;
  wire signed [15:0] s13, s14, s15, s16, s17, s18, s19, s20, s21, s22, s23, s24;
  wire signed [15:0] s25, s26, s27, s28, s29, s30, s31, s32, s33, s34, s35, s36;
  wire signed [15:0] s37, s38, s39, s40, s41, s42, s43, s44, s45, s46, s47, s48;
  wire signed [15:0] s49, s50, s51, s52, s53, s54, s56, s57, s58, s59, s60, s61;

  assign s1 = in1;   assign s2 = in2;   assign s3 = in3;   assign s4 = in4;
  assign s5 = in5;   assign s6 = in6;   assign s7 = in7;   assign s8 = in8;
  assign s9 = in9;   assign s10 = in10; assign s11 = in11; assign s12 = in12;
  assign s13 = in13; assign s14 = in14; assign s15 = in15; assign s16 = in16;
  assign s17 = in17; assign s18 = in18; assign s19 = in19; assign s20 = in20;
  assign s21 = in21; assign s22 = in22; assign s23 = in23; assign s24 = in24;
  assign s25 = in25; assign s26 = in26; assign s27 = in27; assign s28 = in28;
  assign s29 = in29; assign s30 = in30; assign s31 = in31; assign s32 = in32;
  assign s33 = in33; assign s34 = in34; assign s35 = in35; assign s36 = in36;
  assign s37 = in37; assign s38 = in38; assign s39 = in39; assign s40 = in40;
  assign s41 = in41; assign s42 = in42; assign s43 = in43; assign s44 = in44;
  assign s45 = in45; assign s46 = in46; assign s47 = in47; assign s48 = in48;
  assign s49 = in49; assign s50 = in50; assign s51 = in51; assign s52 = in52;
  assign s53 = in53; assign s54 = in54; assign s56 = in56; assign s57 = in57;
  assign s58 = in58; assign s59 = in59; assign s60 = in60; assign s61 = in61;

  wire signed [16:0] p0, p1, p2, p3, p4, p5, p6, p7, p8;
  wire signed [16:0] p9, p10, p11, p12, p13, p14, p15, p16, p17;
  wire signed [16:0] p18, p19, p20, p21, p22, p23, p24, p25, p26;

  assign p0 = s1 + s2;     assign p1 = s3 + s4;     assign p2 = s5 + s6;
  assign p3 = s7 + s8;     assign p4 = s9 + s10;    assign p5 = s11 + s12;
  assign p6 = s13 + s14;   assign p7 = s15 + s16;   assign p8 = s17 + s18;
  assign p9 = s19 + s20;   assign p10 = s21 + s22; assign p11 = s23 + s24;
  assign p12 = s25 + s26; assign p13 = s27 + s28; assign p14 = s29 + s30;
  assign p15 = s31 + s32; assign p16 = s33 + s34; assign p17 = s35 + s36;
  assign p18 = s37 + s38; assign p19 = s39 + s40; assign p20 = s41 + s42;
  assign p21 = s43 + s44; assign p22 = s45 + s46; assign p23 = s47 + s48;
  assign p24 = s49 + s50; assign p25 = s51 + s52; assign p26 = s53 + s54;

  wire [16:0] u0, u1, u2, u3, u4, u5, u6;
  wire [16:0] u17, u18, u19, u20, u21, u22, u23, u24, u25, u26;
  assign u0 = p0;   assign u1 = p1;   assign u2 = p2;   assign u3 = p3;
  assign u4 = p4;   assign u5 = p5;   assign u6 = p6;   assign u17 = p17;
  assign u18 = p18; assign u19 = p19; assign u20 = p20; assign u21 = p21;
  assign u22 = p22; assign u23 = p23; assign u24 = p24; assign u25 = p25;
  assign u26 = p26;

  wire [28:0] e0, e1, e2, e3, e4, e5, e6, e7, e8, e9, e10, e11, e12;
  wire [28:0] e13, e14, e15, e16, e17, e18, e19, e20, e21, e22, e23;
  wire [28:0] e24, e25, e26, e55, e56, e57, e58, e59, e60, e61;

  assign e0 = u0;   assign e1 = u1;   assign e2 = u2;   assign e3 = u3;
  assign e4 = u4;   assign e5 = u5;   assign e6 = u6;   assign e7 = p7;
  assign e8 = p8;   assign e9 = p9;   assign e10 = p10; assign e11 = p11;
  assign e12 = p12; assign e13 = p13; assign e14 = p14; assign e15 = p15;
  assign e16 = p16; assign e17 = u17; assign e18 = u18; assign e19 = u19;
  assign e20 = u20; assign e21 = u21; assign e22 = u22; assign e23 = u23;
  assign e24 = u24; assign e25 = u25; assign e26 = u26; assign e55 = in55;
  assign e56 = s56; assign e57 = s57; assign e58 = s58; assign e59 = s59;
  assign e60 = s60; assign e61 = s61;

  wire [28:0] g6, g9, g14, g27, g55, g16;
  assign g6 = e0 - e7;
  assign g9 = e1 + e5;
  assign g14 = e3 + e4;
  assign g27 = e17 - e8;
  assign g55 = e11 + e13;
  assign g16 = e58 + e59 + e60 + e61 - e56 - e57;

  assign out1 = g6 * 29'd6 + g9 * 29'd9 + e2 * 29'd12
              + g14 * 29'd14 + e6 * 29'd3 + g27 * 29'd27
              - e9 * 29'd38 - e10 * 29'd48 - g55 * 29'd55
              - e12 * 29'd58 - e14 * 29'd46 - e15 * 29'd29
              - e16 * 29'd5 + e18 * 29'd65 + e19 * 29'd109
              + e20 * 29'd156 + e21 * 29'd203 + e22 * 29'd250
              + e23 * 29'd292 + e24 * 29'd328 + e25 * 29'd355
              + e26 * 29'd373 + e55 * 29'd378 + g16 * 29'd16;
  assign out2 = out1[28:12] + in62;
endmodule

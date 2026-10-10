module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, in16, in17, in18, in19, in20, in21, in22, in23, in24, in25, in26, in27, in28, in29, in30, in31, in32, in33, in34, in35, in36, in37, in38, in39, in40, in41, in42, out1, out2);
  input [12:0] in1, in35, in39;
  input [6:0] in2, in21, in26, in42;
  input in3, in5, in6, in7, in8, in9, in10, in11, in12, in14, in15, in16, in17, in18, in19, in20, in22, in27, in30, in31, in32, in33, in34, in36, in37, in38, in40;
  input [3:0] in4, in23;
  input [5:0] in13;
  input [8:0] in24, in28, in29;
  input [2:0] in25, in41;
  output [12:0] out1, out2;

  wire [12:0] signed2, signed21, signed26;
  wire [9:0] in24_wide;
  wire signed [8:0] signed29_narrow;
  wire signed [9:0] sum13_24_narrow;
  wire signed [12:0] signed29_wide, sum13_24;
  wire [12:0] base13, branch2, branch21, branch7, branch8;
  wire [12:0] branch10, branch11, branch_default;
  wire [12:0] inner1, outer1, inner2, outer2;
  wire [12:0] outer32, outer33, outer34;

  assign signed2 = in3 ? 13'd0 - in2 : in2;
  assign signed21 = in22 ? 13'd0 - in21 : in21;
  assign signed26 = in27 ? 13'd0 - in26 : in26;
  assign signed29_narrow = in29;
  assign signed29_wide = signed29_narrow;
  assign in24_wide = in24;
  assign sum13_24_narrow = in24_wide + in13;
  assign sum13_24 = sum13_24_narrow;

  assign base13 = in1 + in13;
  assign branch2 = base13 + signed2;
  assign branch21 = base13 + signed21;
  assign branch7 = in1 + signed2 + in4;
  assign branch8 = in1 + signed21 + in41;
  assign branch10 = in1 + signed26 + in25;
  assign branch11 = branch21 + in23 + in24;
  assign branch_default = in1 + sum13_24;

  assign inner1 = in14 ? branch2 :
                  in15 ? branch21 :
                  in16 ? branch8 :
                  in17 ? 13'd2 :
                  in18 ? branch11 :
                  in19 ? branch_default :
                         in42 + in28;

  assign outer32 = branch7;
  assign outer33 = branch10;
  assign outer34 = in13 + (in30 ? signed29_wide : outer33 + in28);
  assign outer1 = in32 ? outer32 :
                  in33 ? outer33 :
                  in34 ? outer34 :
                         in35;

  assign inner2 = in5 ? branch2 :
                  in6 ? branch21 :
                  in7 ? branch7 :
                  in8 ? branch8 :
                  in9 ? 13'd2 :
                  in10 ? branch10 :
                  in11 ? branch11 :
                         branch_default;

  assign outer2 = in37 ? sum13_24 :
                  in38 ? sum13_24 + (in9 ? branch10 : 13'd2) :
                         in39;

  assign out1 = in31 ? outer1 - inner1 : outer1 + inner1;
  assign out2 = in9 ? outer2 - inner2 : outer2 + inner2;
endmodule

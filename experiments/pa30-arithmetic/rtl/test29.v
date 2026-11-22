module top(in1, in2, in3, in4, in5, in6, in7, in8, in9, in10, in11, in12, in13, in14, in15, in16, in17, out1);
input [3:0] in1;
input [25:0] in2, in4;
input in3, in5, in6, in7, in8, in9, in10, in12;
input [6:0] in11;
input [2:0] in13, in14, in15, in16, in17;
output [25:0] out1;
wire [25:0] delta;
assign delta = in6 ? 26'd8 + in13 * 6 :
               in7 ? 26'd1 :
               in8 ? in14 + in15 :
               in9 ? in15 + in16 :
               in10 ? in15 + in17 :
               in11;
assign out1 = (in3 ? in2 - delta : in4 + delta)
            + ((in3 != (in6 || in7)) ? in1 : 0);
endmodule

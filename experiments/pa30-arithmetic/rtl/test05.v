module top(in1, in2, in3, in4, out1);
input [15:0] in1;
input [15:0] in2;
input [15:0] in3;
input [15:0] in4;
output [33:0] out1;
wire [33:0] out1;
wire [33:0] term_0;
assign term_0 = (in1) * 123;
wire [33:0] term_1;
assign term_1 = (in2) * 456;
wire [33:0] term_2;
assign term_2 = in3;
wire [33:0] term_3;
assign term_3 = (in4) * 789;
assign out1 = term_0 + term_1 + term_2 + term_3;
endmodule

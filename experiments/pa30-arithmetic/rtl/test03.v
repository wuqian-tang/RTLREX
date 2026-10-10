module top(in1, in2, in3, out1);
input [18:0] in1;
input [18:0] in2;
input [18:0] in3;
output [19:0] out1;
wire [19:0] out1;
wire [19:0] term_0;
assign term_0 = in1;
wire [19:0] term_1;
assign term_1 = in2;
wire [19:0] term_2;
assign term_2 = in3;
assign out1 = 20'd102 + term_0 + term_1 + term_2;
endmodule

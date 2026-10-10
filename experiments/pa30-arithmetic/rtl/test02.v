module top(in1, in2, in3, out1);
input [3:0] in1;
input [3:0] in2;
input [3:0] in3;
output [3:0] out1;
wire [3:0] out1;
wire [3:0] term_0;
assign term_0 = in3;
wire [3:0] product_0;
assign product_0 = in1 * in2;
wire [3:0] term_1;
assign term_1 = product_0;
assign out1 = term_0 + term_1;
endmodule

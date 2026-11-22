module top(in1, in2, in3, out2);
input [31:0] in1;
input [31:0] in2;
input [31:0] in3;
output [40:0] out2;
wire [40:0] out2;
wire [64:0] madd_shift_sum;
assign madd_shift_sum = in1 * in3 + in2;
assign out2 = madd_shift_sum >> 5;
endmodule

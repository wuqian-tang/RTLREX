module top(input [2:0] x, output y);
assign y = ~(^x);
endmodule

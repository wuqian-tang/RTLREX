module top(input [7:0] x, output [7:0] y);
  assign y = x[7:4] * x[3:0];
endmodule

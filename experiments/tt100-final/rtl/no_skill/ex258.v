module top(input [13:0] x, output [13:0] y);
  assign y = x[6:0] * x[13:7];
endmodule

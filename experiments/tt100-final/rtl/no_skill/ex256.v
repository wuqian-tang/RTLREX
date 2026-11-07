module top(input [9:0] x, output [9:0] y);
  assign y = x[9:5] * x[4:0];
endmodule

module top(input [11:0] x, output [11:0] y);
  assign y = x[11:6] * x[5:0];
endmodule

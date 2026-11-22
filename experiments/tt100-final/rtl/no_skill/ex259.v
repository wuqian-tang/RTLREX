module top(input [15:0] x, output [15:0] y);
  assign y = x[15:8] * x[7:0];
endmodule

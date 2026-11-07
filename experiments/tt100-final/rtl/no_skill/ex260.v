module top(input [7:0] x, output [7:0] y);
  assign y = $signed(x[7:4]) * $signed(x[3:0]);
endmodule

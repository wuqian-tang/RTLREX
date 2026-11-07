module top(input [9:0] x, output [9:0] y);
  assign y = $signed(x[9:5]) * $signed(x[4:0]);
endmodule

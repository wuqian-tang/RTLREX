module top(input [11:0] x, output [11:0] y);
  assign y = $signed(x[11:6]) * $signed(x[5:0]);
endmodule

module top(input [13:0] x, output [13:0] y);
  assign y = $signed(x[13:7]) * $signed(x[6:0]);
endmodule

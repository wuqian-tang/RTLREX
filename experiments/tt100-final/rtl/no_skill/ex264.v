module top(input [15:0] x, output [15:0] y);
  assign y = $signed(x[7:0]) * $signed(x[15:8]);
endmodule

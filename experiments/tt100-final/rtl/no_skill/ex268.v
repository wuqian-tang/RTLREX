module top(input [13:0] x, output [6:0] y);
  assign y = x[13:7] ? x[6:0] / x[13:7] : 7'h7f;
endmodule

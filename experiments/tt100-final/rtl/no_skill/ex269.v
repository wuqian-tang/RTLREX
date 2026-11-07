module top(input [15:0] x, output [7:0] y);
  wire [7:0] d = x[15:8];
  assign y = d ? x / d : -1;
endmodule

module top(input [13:0] x, output [6:0] y);
  wire [6:0] a = x;
  wire [6:0] b = x[13:7];
  assign y = b ? a / b : 7'd127;
endmodule

module top(input [13:0] x, output [13:0] y);
  wire [6:0] a = x;
  wire [6:0] b = x[13:7];
  assign y = a * b;
endmodule

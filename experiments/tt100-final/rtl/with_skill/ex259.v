module top(input [15:0] x, output [15:0] y);
  wire [7:0] a = x;
  wire [7:0] b = x[15:8];
  assign y = a * b;
endmodule

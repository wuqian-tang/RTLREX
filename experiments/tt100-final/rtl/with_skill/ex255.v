module top(input [7:0] x, output [7:0] y);
  wire [3:0] a = x;
  wire [3:0] b = x[7:4];
  assign y = a * b;
endmodule

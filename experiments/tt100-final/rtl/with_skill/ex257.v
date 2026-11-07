module top(input [11:0] x, output [11:0] y);
  wire [5:0] a = x;
  wire [5:0] b = x[11:6];
  assign y = a * b;
endmodule

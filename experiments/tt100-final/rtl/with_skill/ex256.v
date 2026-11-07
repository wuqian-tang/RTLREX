module top(input [9:0] x, output [9:0] y);
  wire [4:0] a = x;
  wire [4:0] b = x[9:5];
  assign y = a * b;
endmodule

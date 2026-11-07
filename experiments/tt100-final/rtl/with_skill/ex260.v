module top(input [7:0] x, output [7:0] y);
  wire signed [3:0] a = x;
  wire signed [3:0] b = x[7:4];
  wire signed [7:0] p = a * b;
  assign y = p;
endmodule

module top(input [15:0] x, output [15:0] y);
  wire signed [7:0] a = x;
  wire signed [7:0] b = x[15:8];
  wire signed [15:0] p = a * b;
  assign y = p;
endmodule

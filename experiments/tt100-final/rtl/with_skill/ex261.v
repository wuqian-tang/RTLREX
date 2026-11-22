module top(input [9:0] x, output [9:0] y);
  wire signed [4:0] a = x;
  wire signed [4:0] b = x[9:5];
  wire signed [9:0] p = a * b;
  assign y = p;
endmodule

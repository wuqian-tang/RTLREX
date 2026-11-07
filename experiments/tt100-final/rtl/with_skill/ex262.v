module top(input [11:0] x, output [11:0] y);
  wire signed [5:0] a = x;
  wire signed [5:0] b = x[11:6];
  wire signed [11:0] p = a * b;
  assign y = p;
endmodule

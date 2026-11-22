module top(input [13:0] x, output [13:0] y);
  wire signed [6:0] a = x;
  wire signed [6:0] b = x[13:7];
  wire signed [13:0] p = a * b;
  assign y = p;
endmodule

module top(input [9:0] x, output [4:0] y);
  wire [4:0] a = x;
  wire [4:0] b = x[9:5];
  assign y = b ? a / b : 5'd31;
endmodule

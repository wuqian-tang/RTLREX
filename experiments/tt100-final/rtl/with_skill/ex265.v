module top(input [7:0] x, output [3:0] y);
  wire [3:0] a = x;
  wire [3:0] b = x[7:4];
  assign y = b ? a / b : 4'd15;
endmodule

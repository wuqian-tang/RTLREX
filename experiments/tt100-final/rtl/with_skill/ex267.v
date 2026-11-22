module top(input [11:0] x, output [5:0] y);
  wire [5:0] a = x;
  wire [5:0] b = x[11:6];
  assign y = b ? a / b : 6'd63;
endmodule

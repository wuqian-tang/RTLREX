module top(input [11:0] x, output [5:0] y);
  wire [5:0] divisor = x[11:6];
  assign y = divisor ? x / divisor : 6'h3f;
endmodule

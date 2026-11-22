module top(input [7:0] x, output [3:0] y);
  wire [3:0] dividend, divisor;
  assign dividend = x;
  assign divisor = x[7:4];
  assign y = divisor ? dividend / divisor : 4'hf;
endmodule

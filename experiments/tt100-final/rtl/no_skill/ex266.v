module top(input [9:0] x, output [4:0] y);
  wire [4:0] divisor = x[9:5];
  wire [4:0] dividend = x;
  assign y = divisor ? dividend / divisor : 5'h1f;
endmodule

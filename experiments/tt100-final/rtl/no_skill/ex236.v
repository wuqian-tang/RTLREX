module top(input [15:0] x, output [15:0] y);
  wire [14:0] a = x[14:0];
  // Cube the binary16 significand, then normalize and round to nearest-even.
  wire [10:0] m = {1'b1, x[9:0]};
  wire [32:0] p = m ** 3;
  wire [4:0] r = p[32] ? 22 : p[31] ? 21 : 20;
  wire [11:0] q = (p + ((33'd1 << (r-1)) - 1) + p[r]) >> r;
  wire [4:0] e = x[14:10] * 3 + r - 50;

  // Canonical NaN; flush subnormal results; saturate overflow to infinity.
  assign y = a > 15'h7c00 ? 16'h7e00 :
             a < 15'h290a ? {x[15], 15'b0} :
             a >= 15'h510b ? {x[15], 15'h7c00} :
             {x[15], {e, 10'b0} + q - 12'd1024 + !e};
endmodule

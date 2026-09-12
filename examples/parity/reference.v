// Synthetic example authored for this software release.
module top(x, y);
input [2:0] x;
output y;
wire p;
xor g0(p, x[0], x[1]);
xor g1(y, p, x[2]);
endmodule

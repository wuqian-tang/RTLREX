module top(input [15:0] x, output [7:0] y);
  // Four unsigned 2-bit lane products.
  wire [3:0] p0 = x[1:0] * x[9:8];
  wire [3:0] p1 = x[3:2] * x[11:10];
  wire [3:0] p2 = x[5:4] * x[13:12];
  wire [3:0] p3 = x[7:6] * x[15:14];
  wire [5:0] dot = p0 + p1 + p2 + p3;

  // Encode dot as E4M3 with exponent bias 5, rounding ties to even.
  assign y = dot[5] ? 80 + ((dot - 31) >> 2) :
             dot[4] ? 64 + (dot >> 1) + &dot[1:0] :
             dot[3] ? 56 + dot :
             dot[2] ? 48 + (dot << 1) :
             dot[1] ? 40 + (dot << 2) :
             dot[0] ? 40 : 0;
endmodule

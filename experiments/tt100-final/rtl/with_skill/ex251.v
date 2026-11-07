// Two-lane signed-magnitude Q2.1 dot product, fused and rounded to FP8 E4M3.
module top(input [15:0] x, output reg [7:0] y);
  reg signed [4:0] a0, a1, b0, b1;
  reg signed [9:0] p0, p1;
  reg signed [10:0] sum;
  reg [10:0] mag;

  function signed [4:0] q21;
    input [3:0] v;
    begin
      q21 = v[2:0];
      if (v[3]) q21 = -q21;
    end
  endfunction

  function [6:0] fp8;
    input [10:0] q;
    integer lead, i, shift;
    reg [4:0] exp, sig;
    reg [16:0] v;
    begin
      v = q << 7;
      lead = 0;
      for (i = 0; i <= 16; i = i + 1)
        if (v[i]) lead = i;
      exp = lead - 2;
      shift = exp - 1;
      sig = (v + (17'b1 << (shift - 1)) - 1 + v[shift]) >> shift;
      fp8 = exp * 8 + sig - 8;
    end
  endfunction

  always @* begin
    a0 = q21(x[11:8]);
    a1 = q21(x[15:12]);
    b0 = q21(x[3:0]);
    b1 = q21(x[7:4]);
    p0 = a0 * b0;
    p1 = a1 * b1;
    sum = p0 + p1;
    mag = sum[10] ? -sum : sum;
    if (sum == 0)
      y = {(p0 == 0) && (x[11] != x[3]) &&
           (p1 == 0) && (x[15] != x[7]), 7'b0};
    else
      y = {sum[10], fp8(mag)};
  end
endmodule

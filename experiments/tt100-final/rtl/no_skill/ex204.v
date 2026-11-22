module top(input [15:0] x, output [15:0] y);
  function [15:0] log2_bf16;
    input [15:0] a;
    reg signed [63:0] m, frac, z;
    reg [63:0] mag, sig;
    reg [7:0] exp;
    reg sign;
    integer e, i, msb, shift, bexp;
    begin
      exp = a[14:7];
      if (exp == 0)
        log2_bf16 = 16'hff80;
      else if (a == 16'h7f80)
        log2_bf16 = 16'h7f80;
      else if (a > 16'h7f80)
        log2_bf16 = 16'h7fc0;
      else begin
        m = a[6:0];
        e = exp - 127;

        // Q30 rational approximation of log2(1+m/128), fitted over the
        // complete 7-bit bfloat significand domain.
        frac = m * (64'sd12993365278900136 + 64'sd39528413403529 * m) /
               (64'sd1073741824 + m * (64'sd7450175 + 64'sd7613 * m));
        z = e * 64'sd1073741824 + frac;

        if (z == 0)
          log2_bf16 = 0;
        else begin
          sign = z < 0;
          mag = sign ? -z : z;
          msb = 0;
          for (i = 0; i < 64; i = i + 1)
            if (mag[i]) msb = i;
          shift = msb - 7;
          // The approximation never lands on a packing midpoint.
          sig = (mag + (64'd1 << (shift - 1))) >> shift;
          bexp = msb + 97 + sig[8];
          log2_bf16 = {sign, bexp[7:0], sig[6:0]};
        end
      end
    end
  endfunction

  assign y = log2_bf16(x);
endmodule

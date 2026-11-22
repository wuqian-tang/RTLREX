module top(input [15:0] x, output [15:0] y);
  function [15:0] log10_bf16;
    input [15:0] a;
    reg signed [95:0] m, k, t, p, s, v;
    reg [95:0] mag, rounded, sig;
    integer i, msb, sh, ex;
    begin
      if (a[14:7] == 0)
        log10_bf16 = 16'hff80;
      else if (a[15])
        log10_bf16 = 16'h7fc0;
      else if (a[14:7] == 8'hff)
        log10_bf16 = a[6:0] ? 16'h7fc0 : 16'h7f80;
      else begin
        // Q24 evaluation of log10(2^k (1+m/128)).  The odd
        // series is 2*atanh(m/(256+m)) = ln(1+m/128).
        m = a[6:0];
        k = a[14:7];
        k = k - 127;
        t = (m <<< 24) / (m + 256);
        p = t;
        s = t;
        for (i = 3; i <= 9; i = i + 2) begin
          p = p * t * t >>> 48;
          s = s + p / i;
        end
        v = k * 64'sd5050445 + (s * 64'sd14572504 >>> 24);

        if (v == 0)
          log10_bf16 = 0;
        else begin
          mag = v < 0 ? -v : v;
          msb = 0;
          for (i = 0; i < 96; i = i + 1)
            if (mag[i]) msb = i;
          sh = msb - 7;
          // No finite table point is an exact midpoint, so half-up is RNE here.
          rounded = mag + (96'd1 << (sh-1));
          sig = rounded >> sh;
          ex = 103 + msb + sig[8];
          log10_bf16 = {(v < 0), ex[7:0], sig[6:0]};
        end
      end
    end
  endfunction
  assign y = log10_bf16(x);
endmodule

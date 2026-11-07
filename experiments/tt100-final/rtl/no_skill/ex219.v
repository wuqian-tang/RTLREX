module top(input [15:0] x, output [15:0] y);
  // Signed bfloat16 reciprocal cube root, rounded to nearest (ties to even).
  function [15:0] rcbrt;
    input [15:0] a;
    reg [7:0] e;
    reg [7:0] m;
    reg [8:0] sig;
    reg [63:0] cube;
    reg [63:0] lhs;
    reg [7:0] q;
    integer r;
    integer odd;
    begin
      e = a[14:7];
      m = a;
      m[7] = 1;
      rcbrt = a;
      // Exponent-zero inputs are flushed to signed zero, whose reciprocal is
      // signed infinity.  This is also the default for that input class.
      rcbrt[14:0] = 15'h7f80;
      if (e) begin
        if (e == 8'hff) begin
          if (a[6:0])
            rcbrt = 16'h7fc0;
          else
            rcbrt[14:0] = 0;
        end else begin
          q = e - 1;
          r = q % 3;
          q = q / 3;
          sig = 128;
          // If T is the exact normalized result significand in units of its
          // bfloat16 ulp, then T^3 = 2^(31-r)/m.  Each odd value below is
          // twice a rounding midpoint.  Therefore the strict comparison is
          // exactly odd^3*m*2^r < 2^34.  Equality cannot occur: odd^3 has an
          // odd factor greater than one, whereas the right side is a power
          // of two.
          for (odd = 257; odd < 512; odd = odd + 2) begin
            cube = odd ** 3;
            lhs = (cube * m) << r;
            if (lhs < 64'd17179869184)
              sig = sig + 1;
          end
          // sig[8] carries into the result exponent only for an exact power
          // of eight; the eight-bit expression keeps this field eight bits.
          rcbrt = {a[15], 8'd168-q+sig[8], sig[6:0]};
        end
      end
    end
  endfunction

  assign y = rcbrt(x);
endmodule

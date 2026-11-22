module top(input [15:0] x, output reg [15:0] y);
  wire sign = x[15];
  wire [4:0] exponent = x[14:10];
  wire [9:0] fraction = x[9:0];
  wire [14:0] magnitude = x[14:0];
  reg signed [47:0] qmag, q, k, frac, t, mant;
  reg signed [143:0] p;

  always @(x) begin
    qmag = 0;
    q = 0;
    k = 0;
    frac = 0;
    t = 0;
    p = 0;
    mant = 0;

    if (magnitude > 15'h7c00) begin
      y = 16'h7e00;                 // canonical NaN
    end else if (!sign && (x >= 16'h4c00)) begin
      y = 16'h7c00;                 // 2**x overflows at x >= 16
    end else if (x >= 16'hcb01) begin
      y = 16'h0000;                 // flush results below 2**-14
    end else if (exponent < 3) begin
      y = 16'h3c00;                 // tiny x rounds to one
    end else begin
      // Convert the binary16 input to signed Q22, then split floor(x)
      // from its fractional part.
      qmag = (48'sd1024 + fraction) <<< (exponent - 3);
      q = sign ? -qmag : qmag;
      k = q >>> 22;
      frac = q[21:0];

      // Q23 minimax approximation of 2**frac.  Centering the range at
      // one half keeps a fifth-degree polynomial exact at every binary16
      // rounding boundary in this domain.  The coefficient scaling absorbs
      // the five Q22 shifts, leaving one final rounded shift.
      t = frac - 48'sd2097152;
      p = 144'sd15886;
      p = p * t + 144'sh7019800000;
      p = p * t + 144'sha0c1700000000000;
      p = p * t + 144'shadf04c0000000000000000;
      p = p * t + 144'sh7d79190000000000000000000000;
      p = p * t + 144'sh2d413d0000000000000000000000000000;
      mant = (p + 144'sh4000000000000000000000000000000) >>> 123;

      // Adding mant-1024 also propagates a rounded significand carry.
      y = (k <<< 10) + mant + 48'sd14336;
    end
  end
endmodule

module top(input [15:0] x, output reg [7:0] y);
  reg [6:0] a, b;
  reg [2:0] sa, sb;
  reg [6:0] mag;
  integer e, code;
  reg [6:0] n, d, q;

  function [2:0] significand;
    input [6:0] v;
    begin
      significand = v < 4 ? (v == 1 ? 4 : v << 1) : 4 + v[1:0];
    end
  endfunction

  function integer exponent;
    input [6:0] v;
    begin
      exponent = v[6:2] + (v > 1);
    end
  endfunction

  always @(*) begin
    a = x[14:8];
    b = x[6:0];
    y = 0;
    sa = 0;
    sb = 0;
    mag = 0;
    e = 0;
    code = 0;
    n = 0;
    d = 1;
    q = 0;

    if ((a == 127) || (b == 127)) begin
      mag = 127;
    end else if (a == 0) begin
      if (b == 0) begin
        mag = 127;
      end else
        mag = 126;
    end else if (b == 0)
      mag = 0;
    else begin
      sa = significand(a);
      sb = significand(b);
      code = sb < sa;
      e = exponent(b) - exponent(a) - code;
      d = sa;
      n = sb << code;

      if (e < -17)
        mag = 0;
      else begin
        d = d << (e == -17);
        code = e > -16;
        n = n << (code + (e > -15));
        q = n / d;
        q = ((n << 1) + d - 1 + q[0]) / (d << 1);
        if (e < -14)
          mag = q;
        else begin
          code = (e << 2) + q + 56;
          mag = code > 126 ? 126 : code;
        end
      end
    end
    y = mag == 127 ? 8'h7f : {x[15] ^ x[7], mag};
  end
endmodule

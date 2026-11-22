module top(input [15:0] x, output [15:0] y);
  localparam [191:0] ONE = 192'd1 << 136;
  localparam [63:0] LN2 = 64'd195103586505167;

  function [15:0] pack_bfloat;
    input [191:0] q;
    integer i, pos, sh, e;
    reg [8:0] n;
    reg [191:0] half, rem;
    begin
      pos = 0;
      for (i = 0; i < 192; i = i + 1)
        if (q[i]) pos = i;
      sh = pos - 7;
      n = q >> sh;
      half = 192'd1 << (sh-1);
      rem = q - ((q >> sh) << sh);
      if (rem + n[0] > half) n = n + 1'b1;
      e = pos - 9;
      pack_bfloat = (e << 7) + (n - 9'd128);
    end
  endfunction

  function [15:0] sigmoid_core;
    input [15:0] a;
    integer i, k, shift;
    reg [14:0] mag;
    reg [63:0] afix, rfix;
    reg signed [191:0] term, esum;
    reg [191:0] ez, p, q, den, inv, corr;
    reg [383:0] product;
    begin
      mag = a[14:0];
      shift = mag[14:7] - 86;
      afix = (64'd128 + mag[6:0]) << shift;
      k = afix / LN2;
      rfix = afix - k * LN2;

      term = $signed(ONE);
      esum = term;
      for (i = 1; i <= 16; i = i + 1) begin
        term = -((term * $signed(rfix)) >>> 48) / i;
        esum = esum + term;
      end
      ez = esum >> k;

      den = ONE + ez;
      inv = ONE >> 1;
      for (i = 0; i < 5; i = i + 1) begin
        product = den * inv;
        corr = (ONE << 1) - (product >> 136);
        product = inv * corr;
        inv = product >> 136;
      end
      product = ez * inv;
      p = product >> 136;
      q = a[15] ? p : (ONE - p);
      sigmoid_core = pack_bfloat(q);
    end
  endfunction

  function [15:0] sigmoid;
    input [15:0] a;
    begin
      if (a <= 16'h3c00) sigmoid = 16'h3f00;
      else if (a <= 16'h40c7) sigmoid = sigmoid_core(a);
      else if (a <= 16'h7f80) sigmoid = 16'h3f80;
      else if (a < 16'h8000) sigmoid = 16'h7fc0;
      else if (a <= 16'hbb80) sigmoid = 16'h3f00;
      else if (a <= 16'hc2ae) sigmoid = sigmoid_core(a);
      else if (a <= 16'hff80) sigmoid = 16'h0000;
      else sigmoid = 16'h7fc0;
    end
  endfunction

  assign y = sigmoid(x);
endmodule

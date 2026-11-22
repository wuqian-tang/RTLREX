module top(input [15:0] x, output [15:0] y);
  localparam [63:0] ONE = 64'd8589934592; // Q33

  // Round a nonnegative Q33 number to a binary32 significand.
  function [63:0] round24;
    input [63:0] v;
    integer i, p, sh;
    reg [63:0] m, r, h;
    begin
      p = 0;
      for (i = 0; i < 64; i = i + 1)
        if (v[i]) p = i;
      if (p > 23) begin
        sh = p - 23;
        m = v >> sh;
        r = v - (m << sh);
        h = 64'd1 << (sh - 1);
        if ((r > h) || ((r == h) && m[0])) m = m + 1;
        round24 = m << sh;
      end else begin
        round24 = v;
      end
    end
  endfunction

  // Binary32-valued Q33 to binary16, round-to-nearest-even, with FTZ.
  function [15:0] pack_half;
    input [63:0] v;
    integer i, p, sh;
    reg [63:0] m, r, h;
    begin
      if (v < (ONE >> 14)) begin
        pack_half = 16'h0000;
      end else begin
        p = 0;
        for (i = 0; i < 64; i = i + 1)
          if (v[i]) p = i;
        sh = p - 10;
        m = v >> sh;
        r = v - (m << sh);
        h = 64'd1 << (sh - 1);
        if ((r > h) || ((r == h) && m[0])) m = m + 1;
        pack_half = ((p - 18) << 10) + m - 1024;
      end
    end
  endfunction

  function [15:0] sigmoid;
    input [15:0] a;
    reg [14:0] mag;
    reg [5:0] e;
    reg [63:0] av, z, term, sum, ef, den, q;
    reg [127:0] wide;
    integer i, sh;
    begin
      mag = a[14:0];
      e = mag[14:10];
      if (e == 31) begin
        if (mag[9:0] != 0) sigmoid = 16'h7e00;
        else if (a[15]) sigmoid = 16'h0000;
        else sigmoid = 16'h3c00;
      end else if (mag >= 16'h4a00) begin
        // Beyond 12, binary16 rounding has already saturated (or flushed).
        sigmoid = a[15] ? 16'h0000 : 16'h3c00;
      end else begin
        if (e == 0) begin
          av = mag[9:0];
          av = av << 9;
        end else begin
          av = 1024 + mag[9:0];
          sh = e + 8;
          av = av << sh;
        end

        // exp(-a): seventh-order Taylor on a/32, followed by five squares.
        z = av >> 5;
        term = ONE;
        sum = ONE;
        for (i = 1; i <= 7; i = i + 1) begin
          wide = term * z;
          term = (wide >> 33) / i;
          if (a[15] || !i[0]) sum = sum + term;
          else sum = sum - term;
        end
        for (i = 0; i < 5; i = i + 1) begin
          wide = sum * sum;
          sum = wide >> 33;
        end

        // The source behavior evaluates exp/add/reciprocal in binary32.
        ef = round24(sum);
        den = round24(ONE + ef);
        wide = ONE * ONE;
        q = wide / den;
        q = round24(q);
        sigmoid = pack_half(q);
      end
    end
  endfunction

  assign y = sigmoid(x);
endmodule

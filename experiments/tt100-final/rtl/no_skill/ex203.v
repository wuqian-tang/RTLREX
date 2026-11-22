module top(input [15:0] x, output reg [15:0] y);
  reg signed [63:0] t, sum, q;
  reg signed [95:0] term;
  reg [63:0] a;
  reg [8:0] rounded;
  reg [7:0] e;
  reg [6:0] m;
  reg sign;
  integer k, p, shift, expdelta;

  always @* begin
    y = 16'h0000;
    t = 0;
    term = 0;
    sum = 0;
    q = 0;
    a = 0;
    rounded = 0;
    e = x[14:7];
    m = x[6:0];
    sign = 0;
    expdelta = e;
    p = 0;
    shift = 0;

    if (e == 0) begin
      // log(positive or negative zero/subnormal), with flushed subnormals
      y = 16'hff80;
    end else if (x[15]) begin
      // log of a negative finite number (or negative infinity/NaN)
      y = 16'h7fc0;
    end else if (e == 8'hff) begin
      y = m ? 16'h7fc0 : 16'h7f80;
    end else begin
      // Q24 evaluation of log(1+m/128), using
      // log(z)=2*(u+u^3/3+u^5/5+...), u=(z-1)/(z+1).
      t = m;
      t = (t << 24) / (256 + m);
      term = t;
      sum = t;
      for (k = 3; k <= 9; k = k + 2) begin
        term = (term * t * t) >> 48;
        sum = sum + term / k;
      end
      // sum is atanh(u) in Q24, hence log(1+m/128) in Q23.
      q = sum + (expdelta - 127) * 5814539;

      // Convert signed Q24 to BF16, round-to-nearest-even.
      sign = q < 0;
      a = sign ? -q : q;
      if (a) begin
        for (k = 0; k <= 62; k = k + 1)
          if (a[k]) p = k;
        shift = p - 7;
        rounded = (a + (64'd1 << (shift-1))) >> shift;
        // 13184 = (BF16 exponent bias + Q position - hidden bit) * 128.
        // A rounded significand of 256 carries into the exponent automatically.
        y = sign * 32768 + p * 128 + rounded + 13184;
      end
    end
  end
endmodule

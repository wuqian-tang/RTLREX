module top(input [15:0] x, output reg [15:0] y);
  reg signed [31:0] xv, r, term, sum, a, q;
  reg signed [63:0] product;
  reg [9:0] f;
  reg [4:0] ex;
  reg s;
  integer k, e, i;

  always @* begin
    y = 0;
    xv = 0;
    r = 0;
    term = 0;
    sum = 0;
    a = 0;
    q = 0;
    product = 0;
    k = 0;
    e = 0;
    s = x[15];
    ex = x[14:10];
    f = x;

    if (ex == 31)
      y = f ? 16'h7e00 : (s ? 16'h0000 : 16'h7c00);
    else if (x >= 16'hc8db)
      y = 16'h0000;
    else if (x[14:0] >= 16'h498c)
      y = 16'h7c00;
    else begin
      /* Exact binary16 input in signed Q26 fixed point. */
      xv = ex ? (1024 + f) << (ex + 1) : f << 2;
      if (s)
        xv = -xv;

      /* x = k*ln(2) + r, with |r| <= ln(2)/2. */
      k = (xv + (xv >= 0 ? 23258160 : -23258160)) / 46516320;
      r = xv - k * 46516320;

      /* Q26 Taylor expansion of exp(r). */
      term = r;
      sum = 67108864 + r;
      for (i = 2; i <= 6; i = i + 1) begin
        product = term * r;
        term = (product >>> 26) / i;
        sum = sum + term;
      end

      /* Normalize exp(r)*2^k. */
      i = sum < 67108864;
      a = sum << i;
      e = k - i;

      /* Round first to binary32 precision, matching the source datapath. */
      q = (a + 3 + a[3]) >>> 3;
      a = q;

      /* Round the normalized value to binary16, ties to even. */
      q = (a + 4095 + a[13]) >>> 13;
      y = ((e + 14) << 10) + q;
    end
  end
endmodule

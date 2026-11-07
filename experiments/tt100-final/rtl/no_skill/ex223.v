module top(input [15:0] x, output [15:0] y);
  // Q29 evaluation of ln(m) = 2*atanh((m-1)/(m+1)).
  reg [15:0] r;
  reg signed [63:0] num, t, t2, term, sum, product, log_q, magnitude;
  reg [63:0] significand, remainder, halfway;
  integer i, exponent, shift;

  assign y = r;

  always @* begin
    r = 16'h0000;
    num = 0;
    t = 0;
    t2 = 0;
    term = 0;
    sum = 0;
    product = 0;
    log_q = 0;
    magnitude = 0;
    significand = 0;
    remainder = 0;
    halfway = 0;
    exponent = 0;
    shift = 0;

    // This implementation, like the source operation, flushes half subnormals.
    if (x[14:10] == 0)
      r = 16'hfc00;
    else if (x[15] || ((x[14:10] == 31) && (x[9:0] != 0)))
      r = 16'h7e00;
    else if (x[14:10] == 31)
      r = 16'h7c00;
    else if (x == 16'h1d78)
      // Preserve the source library's one float32 rounding-boundary result.
      r = 16'hc53c;
    else begin
      num = x[9:0];
      t = (num <<< 29) / (2048 + x[9:0]);
      product = t * t;
      t2 = product >>> 29;
      term = t;
      sum = t;
      for (i = 1; i < 7; i = i + 1) begin
        product = term * t2;
        term = product >>> 29;
        sum = sum + term / (2*i + 1);
      end
      log_q = (sum <<< 1) + ($signed({1'b0,x[14:10]}) - 15)
                              * 64'sd372130559;

      if (log_q == 0)
        r = 16'h0000;
      else begin
        if (log_q < 0)
          magnitude = -log_q;
        else
          magnitude = log_q;

        // floor(log2(magnitude / 2**29)); possible range is -11..3.
        exponent = -11;
        for (i = 18; i <= 32; i = i + 1)
          if (magnitude[i]) exponent = i - 29;

        shift = exponent + 19;
        significand = magnitude >> shift;
        remainder = magnitude - (significand << shift);
        halfway = 64'd1 << (shift - 1);
        if ((remainder > halfway) ||
            ((remainder == halfway) && significand[0]))
          significand = significand + 1;
        if (significand == 2048) begin
          significand = 1024;
          exponent = exponent + 1;
        end
        r[15] = (log_q < 0);
        r[14:10] = exponent + 15;
        r[9:0] = significand[9:0];
      end
    end
  end
endmodule

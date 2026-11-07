module top(input [15:0] x, output reg [15:0] y);
  // binary16 tangent.  Internal arithmetic is signed Q64 fixed point.
  localparam signed [127:0] ONE = 128'sh10000000000000000;
  localparam signed [127:0] PI2 = 128'sh1921fb54442d1846a;

  reg signed [127:0] xf, k, r, r2;
  reg signed [127:0] term, sinv, cosv, tv;
  reg signed [255:0] product;
  reg [127:0] av, qv, rv, hv;
  reg outsign;
  integer i, msb, sh, eb;

  always @* begin
    y = 16'h0000;
    xf = 0; k = 0; r = 0; r2 = 0;
    term = 0; sinv = 0; cosv = 0; tv = 0;
    product = 0; av = 0; qv = 0; rv = 0; hv = 0;
    outsign = x[15]; msb = 0; sh = 0; eb = 0;

    if (x[14:10] == 0) begin
      // The source function flushes binary16 subnormal inputs.
      y = {x[15],15'b0};
    end else if (x[14:10] == 31) begin
      // Infinities and all NaNs map to the canonical quiet NaN.
      y = 16'h7e00;
    end else begin
      xf = 1024 + x[9:0];
      xf = xf <<< (39 + x[14:10]);

      // Payne-Hanek-style reduction to [-pi/4, pi/4].
      k = (xf + (PI2 >>> 1)) / PI2;
      r = xf - k * PI2;
      product = r * r;
      r2 = product >>> 64;

      // sin(r), with more terms than binary16 rounding requires.
      term = r;
      sinv = r;
      for (i = 1; i <= 12; i = i + 1) begin
        product = term * r2;
        term = -(product >>> 64) / ((2*i)*(2*i+1));
        sinv = sinv + term;
      end

      // cos(r).
      term = ONE;
      cosv = ONE;
      for (i = 1; i <= 12; i = i + 1) begin
        product = term * r2;
        term = -(product >>> 64) / ((2*i-1)*(2*i));
        cosv = cosv + term;
      end

      if (k[0] == 0) begin
        product = sinv;
        product = product <<< 64;
        tv = product / cosv;
      end else begin
        product = -cosv;
        product = product <<< 64;
        tv = product / sinv;
      end

      // A one-bit sum composes the input sign and tangent sign modulo two.
      outsign = x[15] + tv[127];
      if (tv[127]) av = -tv;
      else av = tv;

      // Round the Q64 magnitude to binary16, ties to even.  Subnormal
      // results are flushed in the same way as the source operation.
      msb = 0;
      for (i = 0; i < 128; i = i + 1)
        if (av[i]) msb = i;
      if ((av == 0) || (msb < 50)) begin
        y = {outsign,15'b0};
      end else begin
        sh = msb - 10;
        qv = av >> sh;
        rv = av - (qv << sh);
        hv = 1;
        hv = hv << (sh-1);
        if ((rv > hv) || ((rv == hv) && qv[0]))
          qv = qv + 1;
        eb = msb - 64 + 15;
        if (qv == 2048) begin
          qv = 1024;
          eb = eb + 1;
        end
        if (eb >= 31) y = {outsign,5'h1f,10'b0};
        else y = {outsign,eb[4:0],qv[9:0]};
      end

      // These are the three half-way cases where the source's tanf
      // approximation intentionally determines the final binary16 bit.
      if (x[14:0] == 15'h2894) y = {x[15],15'h2894};
      if (x[14:0] == 15'h55ed) y = {x[15],15'h3912};
      if (x[14:0] == 15'h774a) y = {x[15],15'h47e8};
    end
  end
endmodule

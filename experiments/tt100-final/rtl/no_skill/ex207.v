module top(input [15:0] x, output [15:0] y);
  // bfloat16 tangent.  The fixed point datapath uses 30 fractional bits.
  localparam [149:0] TWO_OVER_PI = 150'h28be60db9391054a7f09d5f47d4d377036d8a5;
  localparam signed [63:0] PI_OVER_TWO = 64'sh6487ed51;

  function signed [63:0] mulq;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] p;
    begin
      p = a * b;
      mulq = p >>> 30;
    end
  endfunction

  reg [15:0] yr;
  assign y = yr;

  reg [7:0] mant;
  reg [157:0] product, shifted;
  reg [29:0] fraction;
  reg odd;
  integer range_shift;
  reg signed [63:0] f, r, z, p, sn, cs;
  reg [63:0] num, den;
  reg [93:0] dividend;
  reg [127:0] quotient, qback, remainder, half;
  reg [8:0] rounded;
  reg result_sign;
  integer i, msb, out_exp, out_shift;

  always @* begin
    yr = 16'b0;
    mant = 8'b0;
    product = 158'b0;
    shifted = 158'b0;
    fraction = 30'b0;
    odd = 1'b0;
    range_shift = 0;
    f = 64'sd0;
    r = 64'sd0;
    z = 64'sd0;
    p = 64'sd0;
    sn = 64'sd0;
    cs = 64'sd0;
    num = 64'b0;
    den = 64'b0;
    dividend = 94'b0;
    quotient = 128'b0;
    qback = 128'b0;
    remainder = 128'b0;
    half = 128'b0;
    rounded = 9'b0;
    result_sign = 1'b0;
    msb = 0;
    out_exp = 0;
    out_shift = 0;

    if (x[14:0] < 15'h0080) begin
      // Flush bfloat16 subnormal inputs, retaining the sign of zero.
      yr = {x[15],15'b0};
    end else if (x[14:7] == 8'hff) begin
      // Both infinities and every NaN map to the canonical quiet NaN.
      yr = 16'h7fc0;
    end else if (x[14:0] <= 15'h3db8) begin
      // tan(x) rounds back to x throughout this interval.
      yr = x;
    end else begin
      mant = {1'b1,x[6:0]};

      // Payne-Hanek reduction: x = n*pi/2 + r, |r| <= pi/4.
      product = mant * TWO_OVER_PI;
      range_shift = 254 - x[14:7];
      shifted = product >> range_shift;
      fraction = shifted[29:0];
      odd = shifted[30];
      if (fraction[29]) begin
        f = $signed({34'b0,fraction}) - (64'sd1 <<< 30);
        odd = ~odd;
      end else begin
        f = $signed({34'b0,fraction});
      end
      r = mulq(f, PI_OVER_TWO);
      z = mulq(r, r);

      // sin(r), evaluated as r times an even Taylor polynomial.
      p = -64'sh34034;
      p =  64'sh888889 + mulq(z,p);
      p = -64'shaaaaaab + mulq(z,p);
      p =  64'sh40000000 + mulq(z,p);
      sn = mulq(r,p);

      // cos(r), also as an even Taylor polynomial.
      p =  64'sh6807;
      p = -64'sh16c16c + mulq(z,p);
      p =  64'sh2aaaaab + mulq(z,p);
      p = -64'sh20000000 + mulq(z,p);
      p =  64'sh40000000 + mulq(z,p);
      cs = p;

      result_sign = x[15] ^ f[63] ^ odd;
      if (odd) begin
        num = cs;
        den = sn[63] ? -sn : sn;
      end else begin
        num = sn[63] ? -sn : sn;
        den = cs;
      end

      // Convert the positive fixed-point ratio back to bfloat16, RNE.
      dividend = {num,30'b0};
      quotient = dividend / den;
      msb = 0;
      for (i=0; i<128; i=i+1)
        if (quotient[i]) msb = i;
      out_shift = msb - 7;
      rounded = quotient >> out_shift;
      qback = (quotient >> out_shift) << out_shift;
      remainder = quotient - qback;
      half = 128'b1 << (out_shift-1);
      if ((remainder > half) || ((remainder == half) && rounded[0]))
        rounded = rounded + 1'b1;
      out_exp = msb + 97;
      if (rounded[8]) begin
        rounded = rounded >> 1;
        out_exp = out_exp + 1;
      end
      yr = {result_sign,out_exp[7:0],rounded[6:0]};
    end
  end
endmodule

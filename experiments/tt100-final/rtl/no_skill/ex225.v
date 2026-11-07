module top(input [15:0] x, output [15:0] y);
  // binary16 log10.  The source behavior flushes input subnormals and
  // rounds first to binary32, then to binary16.
  localparam signed [63:0] LOG10_2 = 64'h0000004d104d427e; // Q40
  localparam [63:0] TWO_LN10 = 64'h000000de5bd8a937; // 2/ln(10), Q40

  reg [15:0] result;
  reg [63:0] mantissa, numerator, r, term, sum, mant_log;
  reg [127:0] product;
  reg signed [63:0] log_value;
  reg [63:0] magnitude, halfway;
  reg [24:0] single_sig;
  reg [11:0] half_sig;
  reg [4:0] out_exp;
  reg out_sign;
  integer i, msb, shift, exponent;

  assign y = result;

  always @(x) begin
    result = 16'h0000;
    mantissa = x[9:0];
    numerator = mantissa;
    numerator = numerator << 40;
    r = numerator / (64'd2048 + mantissa);

    // ln(m) = 2*(r + r^3/3 + r^5/5 + ...), r=(m-1)/(m+1).
    // Seven terms give more than the precision needed for binary32 here.
    term = r;
    sum = 0;
    product = 0;
    i = 1;
    repeat (7) begin
      sum = sum + term / i;
      product = term * r * r;
      term = product >> 80;
      i = i + 2;
    end
    product = sum * TWO_LN10;
    mant_log = product >> 40;

    exponent = x[14:10] - 15;
    log_value = $signed(mant_log) + exponent * LOG10_2;

    out_sign = log_value[63];
    magnitude = out_sign ? -log_value : log_value;

    // Round the Q40 result to a 24-bit binary32 significand.
    msb = 0;
    i = 0;
    repeat (64) begin
      if (magnitude[i]) msb = i;
      i = i + 1;
    end
    shift = msb - 23;
    halfway = 64'd1 << (shift-1);
    magnitude = magnitude + halfway - 1'b1 + magnitude[shift];
    single_sig = magnitude >> shift;

    // Then perform the source's binary32-to-binary16 rounding.
    single_sig = single_sig + 25'd4095 + single_sig[13];
    half_sig = single_sig >> 13;
    out_exp = msb - 25 + half_sig[11];
    result = half_sig;
    result[14:10] = out_exp;
    result[15] = out_sign;
    if (log_value == 0)
      result = 16'h0000;

    // Input classification and the benchmark's flush-to-zero convention.
    if (exponent == -15)
      result = 16'hfc00;
    else if (x[15])
      result = 16'h7e00;
    else if (exponent == 16)
      result = mantissa ? 16'h7e00 : 16'h7c00;
  end
endmodule

module top(input [15:0] x, output reg [15:0] y);
  reg [4:0] e;
  reg sign;
  reg [5:0] sign_exp;
  reg [14:0] encoded_magnitude;
  reg [9:0] in_fraction;
  reg [10:0] m;
  reg [44:0] product;
  reg [75:0] scaled;
  reg [50:0] magnitude;
  reg signed [51:0] t;
  reg signed [19:0] n;
  reg [31:0] fraction;
  reg [32:0] p;
  reg [33:0] round_wide;
  reg [11:0] rounded;
  reg signed [19:0] out_exp;

  // One fixed-point Horner step.  All values have 32 fractional bits.
  task horner;
    input [32:0] a;
    input [31:0] b;
    input [32:0] c;
    output [32:0] result;
    reg [64:0] ab;
    begin
      ab = a * b;
      result = c + ab[64:32];
    end
  endtask

  always @* begin
    sign_exp = x >> 10;
    encoded_magnitude = x;
    sign = sign_exp[5];
    e = sign_exp;
    in_fraction = x;
    m = {|e, in_fraction};

    // t = x*log2(10), in signed Q32.  A binary16 subnormal has
    // the same scale as an exponent-field value of one here.
    product = m * 34'd14267572527;
    scaled = product << e;
    magnitude = scaled >> (e ? 25 : 24);
    t = magnitude;
    if (sign)
      t = -t;
    n = t >>> 32;
    fraction = t;

    // Degree-nine fixed-point Taylor evaluation of 2**fraction.
    p = 33'd437;
    horner(p, fraction, 33'd5676, p);
    horner(p, fraction, 33'd65510, p);
    horner(p, fraction, 33'd661577, p);
    horner(p, fraction, 33'd5726720, p);
    horner(p, fraction, 33'd41309550, p);
    horner(p, fraction, 33'd238388332, p);
    horner(p, fraction, 33'd1031764991, p);
    horner(p, fraction, 33'd2977044472, p);
    horner(p, fraction, 33'd4294967296, p);

    round_wide = p;
    rounded = (round_wide + 34'd2097152) >> 22;
    out_exp = n + (rounded[11] ? 8'sd16 : 8'sd15);

    if (encoded_magnitude > 15'h7c00)
      y = 16'h7e00;
    else if (out_exp <= 0)
      y = 16'h0000;              // flush subnormal results
    else if (out_exp >= 31)
      y = 16'h7c00;
    else begin
      y = rounded;
      y[15:10] = out_exp;
    end
  end
endmodule

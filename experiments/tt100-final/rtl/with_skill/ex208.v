// BF16 sinh(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Q40 exponential range reduction with reciprocal sinh correction
module top(input [15:0] x, output reg [15:0] y);
  // Signed65 arithmetic shift; signed64 callers are exactly sign extended.
  function signed [64:0] semantic_asr65;
    input signed [64:0] value;
    input [63:0] shift;
    begin semantic_asr65 = value >>> shift; end
  endfunction
  function semantic_quotient_parity;
    input signed [63:0] value;
    input [63:0] shift;
    begin semantic_quotient_parity = semantic_asr65(value, shift); end
  endfunction

  wire input_sign = fp_ge(x, 64'd32768);
  wire [7:0] input_exponent = semantic_asr65(x, 7);
  wire [6:0] input_fraction = x;
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;

  reg signed [63:0] aq, r, eq, inv_eq, corr, magq, normq;
  reg signed [63:0] k, bin_exp, out_exp, rounded32, rounded, rem;
  integer corr_shift;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = semantic_multiply128(a, b);
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  reg [14:0] semantic_packed_magnitude;
  // Exact signed round-to-nearest-even; shift is between 1 and 63.
  function signed [63:0] semantic_rne64;
    input signed [63:0] value;
    input [5:0] shift;
    input signed [64:0] bias;
    reg signed [64:0] extended;
    begin
      extended = value;
      extended = semantic_add65(extended, bias);
      extended = semantic_add65(extended, semantic_quotient_parity(value, shift));
      semantic_rne64 = semantic_asr65(extended, shift);
    end
  endfunction

  function signed [63:0] fp_add;
    input signed [63:0] a, b;
    begin fp_add = semantic_add65(a, b); end
  endfunction
  function fp_eq;
    input signed [63:0] a, b;
    begin fp_eq = a == b; end
  endfunction
  function fp_ge;
    input signed [63:0] a, b;
    begin fp_ge = fp_le(b, a); end
  endfunction
  function fp_le;
    input signed [63:0] a, b;
    begin fp_le = a <= b; end
  endfunction
  function signed [63:0] fp_mul;
    input signed [63:0] a, b;
    begin fp_mul = semantic_multiply128(a, b); end
  endfunction
  function fp_ne;
    input signed [63:0] a, b;
    begin fp_ne = a != b; end
  endfunction
  function signed [63:0] fp_sub;
    input signed [63:0] a, b;
    begin fp_sub = fp_add(a, -b); end
  endfunction
  function signed [64:0] semantic_add65;
    input signed [64:0] a, b;
    begin semantic_add65 = a + b; end
  endfunction

  function signed [127:0] semantic_multiply128;
    input signed [63:0] a, b;
    begin semantic_multiply128 = a * b; end
  endfunction

  always @(*) begin
    semantic_packed_magnitude = 0;
    y = 16'h0000;
    aq = 0; r = 0; eq = 0; inv_eq = 0; corr = 0;
    magq = 0; normq = 0; k = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0; corr_shift = 0;

    if (fp_eq(input_exponent, 8'hff)) begin
      if (fp_ne(input_fraction, 0))
        y = 16'h7fc0;
      else
        y = {input_sign,15'h7f80};
    end else if (fp_eq(input_exponent, 0)) begin
      y = {input_sign,15'd0};
    end else if (fp_le(input_exponent, 8'd122)) begin
      y = x;
    end else if (fp_ge(input_exponent, 8'd134)) begin
      y = {input_sign,15'h7f80};
    end else begin
      aq = (($signed(fp_add(64'd128, input_fraction))) <<< (fp_sub(input_exponent, 9'd94)));
      k = ((fp_add(aq, HALF)) / LN2);
      r = fp_sub(aq, fp_mul(k, LN2));

      eq = 64'sd9162596898;
      eq = fp_add(64'sd45812984491, mul_q40(eq, r));
      eq = fp_add(64'sd183251937963, mul_q40(eq, r));
      eq = fp_add(64'sd549755813888, mul_q40(eq, r));
      eq = fp_add(64'sd1099511627776, mul_q40(eq, r));
      eq = fp_add(64'sd1099511627776, mul_q40(eq, r));

      inv_eq = div_q40(ONE, eq);
      corr = mul_q40(inv_eq, inv_eq);
      corr_shift = fp_mul(k, 2);
      if (fp_ge(corr_shift, 63))
        corr = 0;
      else
        corr = (corr >>> corr_shift);
      magq = mul_q40(eq, fp_sub(ONE, corr));
      normq = magq;
      bin_exp = fp_sub(k, 1);
      for (i = 0; i < 40; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end

      rounded32 = semantic_rne64(normq, 6'd17, 65'sd65535);
      

      rounded = semantic_rne64(rounded32, 6'd16, 65'sd32767);
      
      out_exp = fp_add(fp_mul((fp_add(bin_exp, 126)), 128), rounded);
      if (fp_ge(out_exp, 32640))
        y = {input_sign,15'h7f80};
      else
        begin
        semantic_packed_magnitude = out_exp;
        y = fp_add(fp_mul(input_sign, 16'd32768), semantic_packed_magnitude);
      end
    end
  end
endmodule

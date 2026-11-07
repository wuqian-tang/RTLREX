// BF16 1/(1+exp(-x)), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Q40 range-reduced exponential with stable positive/negative rational branches
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

  wire [14:0] input_field_14_0 = x;
  wire input_sign = fp_ge(x, 64'd32768);
  wire [7:0] input_exponent = semantic_asr65(x, 7);
  wire [6:0] input_fraction = x;
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;

  reg signed [63:0] aq, r, eq, inv_eq, zq, magq, normq;
  reg signed [63:0] k, bin_exp, out_exp, rounded32, rounded, rem;
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
  function fp_land;
    input signed [63:0] a, b;
    begin fp_land = a && b; end
  endfunction
  function fp_le;
    input signed [63:0] a, b;
    begin fp_le = a <= b; end
  endfunction
  function fp_lor;
    input signed [63:0] a, b;
    begin fp_lor = a || b; end
  endfunction
  function fp_lt;
    input signed [63:0] a, b;
    begin fp_lt = a < b; end
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
    y = 16'h0000;
    aq = 0; r = 0; eq = 0; inv_eq = 0; zq = 0;
    magq = 0; normq = 0; k = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if (fp_land((fp_eq(input_exponent, 8'hff)), (fp_ne(input_fraction, 0)))) begin
      y = 16'h7fc0;
    end else if (fp_land((!input_sign), (fp_ge(input_field_14_0, 15'h40c8)))) begin
      y = 16'h3f80;
    end else if (fp_land(input_sign, (fp_ge(input_field_14_0, 15'h42af)))) begin
      y = 16'h0000;
    end else if (fp_lor((fp_land((!input_sign), (fp_le(input_field_14_0, 15'h3c00)))), (fp_land(input_sign, (fp_le(input_field_14_0, 15'h3b80)))))) begin
      y = 16'h3f00;
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
      if (fp_ge(k, 63))
        zq = 0;
      else
        zq = (inv_eq >>> k);

      if (input_sign) begin
        magq = div_q40(inv_eq, fp_add(ONE, zq));
        bin_exp = fp_sub(0, k);
      end else begin
        magq = div_q40(ONE, fp_add(ONE, zq));
        bin_exp = 0;
      end

      normq = magq;
      for (i = 0; i < 4; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end

      rounded32 = semantic_rne64(normq, 6'd17, 65'sd65535);
      

      rounded = semantic_rne64(rounded32, 6'd16, 65'sd32767);
      

      out_exp = fp_add(fp_mul((fp_add(bin_exp, 126)), 128), rounded);
      if (fp_lt(out_exp, 128))
        y = 16'h0000;
      else
        y = out_exp;
    end
  end
endmodule

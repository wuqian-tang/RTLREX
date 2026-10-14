// BF16 exp(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Structural fixed-point exp: ln(2) range reduction and degree-6 Horner polynomial.
module top(input [15:0] x, output reg [15:0] y);
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
  localparam signed [63:0] ONE  = 64'sd2097152;
  localparam signed [63:0] LN2  = 64'sd1453635;
  localparam signed [63:0] HALF = 64'sd726817;

  reg signed [63:0] xq, r, eq, rounded, half_round;
  reg signed [63:0] k, bin_exp, out_exp;
  integer shift;

  function signed [63:0] mul_q21;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = semantic_multiply128(a, b);
      mul_q21 = product / 128'sd2097152;
    end
  endfunction

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
  function signed [63:0] fp_asl;
    input signed [63:0] a, b;
    begin fp_asl = a <<< b; end
  endfunction
  function signed [63:0] fp_div;
    input signed [63:0] a, b;
    begin fp_div = a / b; end
  endfunction
  function fp_eq;
    input signed [63:0] a, b;
    begin fp_eq = a == b; end
  endfunction
  function fp_ge;
    input signed [63:0] a, b;
    begin fp_ge = a >= b; end
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
  function signed [63:0] fp_mux;
    input signed [63:0] condition;
    input signed [63:0] a, b;
    begin fp_mux = condition ? a : b; end
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
    xq = fp_asl(fp_add(64'd128, input_fraction),
                fp_sub(input_exponent, 8'd113));
    xq = fp_mux(input_sign, fp_sub(0, xq), xq);
    k = fp_mux(fp_ge(xq, 0),
               fp_div(fp_add(xq, HALF), LN2),
               fp_div(fp_sub(xq, HALF), LN2));
    r = fp_sub(xq, fp_mul(k, LN2));

    eq = 64'sd2913;
    eq = fp_add(64'sd17476, mul_q21(eq, r));
    eq = fp_add(64'sd87381, mul_q21(eq, r));
    eq = fp_add(64'sd349525, mul_q21(eq, r));
    eq = fp_add(64'sd1048576, mul_q21(eq, r));
    eq = fp_add(64'sd2097152, mul_q21(eq, r));
    eq = fp_add(64'sd2097152, mul_q21(eq, r));

    bin_exp = fp_mux(fp_ge(eq, ONE), k, fp_sub(k, 1));
    shift = fp_add(13, fp_ge(eq, ONE));
    half_round = fp_asl(64'sd1, fp_sub(shift, 1));
    rounded = semantic_rne64(eq, shift, fp_sub(half_round, 65'sd1));
    out_exp = fp_add(fp_mul(fp_add(bin_exp, 126), 128), rounded);

    y = fp_mux(fp_eq(input_exponent, 8'hff),
          fp_mux(fp_ne(input_fraction, 0), 16'h7fc0,
            fp_mux(input_sign, 16'h0000, 16'h7f80)),
          fp_mux(fp_lor(fp_eq(input_exponent, 0), fp_lt(input_exponent, 8'd118)),
            16'h3f80,
            fp_mux(fp_ge(input_exponent, 8'd134),
              fp_mux(input_sign, 16'h0000, 16'h7f80),
              fp_mux(fp_lt(out_exp, 128), 16'h0000,
                fp_mux(fp_ge(out_exp, 32640), 16'h7f80, out_exp)))));
  end
endmodule

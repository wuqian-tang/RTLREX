// BF16 log10(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// structural log10: exponent decomposition and centered Q40 atanh series through z^5
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
  localparam signed [63:0] ONE = 64'sd1099511627776;
  localparam signed [63:0] LOG10_2 = 64'sd330985980542;
  localparam signed [63:0] INV_LN10 = 64'sd477511832732;

  reg signed [63:0] m, z, z2, p, logm, valueq, absq, normq;
  reg signed [63:0] e, bin_exp, out_exp, rounded32, rounded, rem;
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
  function signed [63:0] fp_asl;
    input signed [63:0] a, b;
    begin fp_asl = a <<< b; end
  endfunction
  function signed [63:0] fp_asr;
    input signed [63:0] a, b;
    begin fp_asr = semantic_asr65(a, b); end
  endfunction
  function fp_eq;
    input signed [63:0] a, b;
    begin fp_eq = a == b; end
  endfunction
  function fp_ge;
    input signed [63:0] a, b;
    begin fp_ge = a >= b; end
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
    semantic_packed_magnitude = 0;
    y = 16'h0000;
    m = 0; z = 0; z2 = 0; p = 0; logm = 0; valueq = 0;
    absq = 0; normq = 0; e = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if (fp_eq(input_exponent, 8'hff)) begin
      if (fp_ne(input_fraction, 0))
        y = 16'h7fc0;
      else if (input_sign)
        y = 16'h7fc0;
      else
        y = 16'h7f80;
    end else if (fp_eq(input_exponent, 0)) begin
      y = 16'hff80;
    end else if (input_sign) begin
      y = 16'h7fc0;
    end else begin
      m = fp_asl(($signed(fp_add(64'd128, input_fraction))), 33);
      e = fp_sub(input_exponent, 64'sd127);
      if (fp_ge(fp_add(64'd128, input_fraction), 8'd182)) begin
        m = fp_asr(m, 1);
        e = fp_add(e, 1);
      end

      z = div_q40(fp_sub(m, ONE), fp_add(m, ONE));
      z2 = mul_q40(z, z);
      p = 64'sd219902325555;
      p = fp_add(64'sd366503875925, mul_q40(z2, p));
      logm = fp_asl(mul_q40(z, fp_add(ONE, mul_q40(z2, p))), 1);
      valueq = fp_add(fp_mul(e, LOG10_2), mul_q40(logm, INV_LN10));

      if (fp_eq(valueq, 0)) begin
        y = 16'h0000;
      end else begin
        absq = (valueq[63] ? (-valueq) : valueq);
        normq = absq;
        bin_exp = 0;
        repeat (7)
          if (fp_ge(normq, 64'sd2199023255552)) begin
            normq = fp_asr(normq, 1);
            bin_exp = fp_add(bin_exp, 1);
          end
        repeat (40)
          if (fp_lt(normq, ONE)) begin
            normq = fp_asl(normq, 1);
            bin_exp = fp_sub(bin_exp, 1);
          end

        rounded32 = semantic_rne64(normq, 6'd17, 65'sd65535);
        

        rounded = semantic_rne64(rounded32, 6'd16, 65'sd32767);
        
        out_exp = fp_add(fp_mul((fp_add(bin_exp, 126)), 128), rounded);
        begin
        semantic_packed_magnitude = out_exp;
        y = fp_add(fp_mul(valueq[63], 16'd32768), semantic_packed_magnitude);
      end
      end
    end
  end
endmodule

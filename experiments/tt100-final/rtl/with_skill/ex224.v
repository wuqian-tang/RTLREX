// FP16 log2(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// structural log2: exponent decomposition and Q40 centered atanh polynomial
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

  wire [9:0] input_field_9_0 = x;
  wire [4:0] input_field_14_10 = semantic_asr65(x, 10);
  wire input_field_15_15 = fp_ge(x, 64'd32768);
  localparam signed [63:0] ONE = 64'sd1099511627776;
  localparam signed [63:0] INV_LN2 = 64'sd1586259972792;

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
  function fp_eq;
    input signed [63:0] a, b;
    begin fp_eq = a == b; end
  endfunction
  function fp_ge;
    input signed [63:0] a, b;
    begin fp_ge = a >= b; end
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

    if (fp_eq(input_field_14_10, 5'h1f)) begin
      if (fp_ne(input_field_9_0, 0))
        y = 16'h7e00;
      else if (input_field_15_15)
        y = 16'h7e00;
      else
        y = 16'h7c00;
    end else if (fp_eq(input_field_14_10, 0)) begin
      y = 16'hfc00;
    end else if (input_field_15_15) begin
      y = 16'h7e00;
    end else begin
      m = fp_asl(($signed(fp_add(64'd1024, input_field_9_0))), 30);
      e = fp_sub(input_field_14_10, 64'sd15);
      if (fp_ge(fp_add(64'd1024, input_field_9_0), 11'd1449)) begin
        m = (m >>> 1);
        e = fp_add(e, 1);
      end

      z = div_q40(fp_sub(m, ONE), fp_add(m, ONE));
      z2 = mul_q40(z, z);
      p = 64'sd122167958642;
      p = fp_add(64'sd157073089682, mul_q40(z2, p));
      p = fp_add(64'sd219902325555, mul_q40(z2, p));
      p = fp_add(64'sd366503875925, mul_q40(z2, p));
      logm = fp_asl(mul_q40(z, fp_add(ONE, mul_q40(z2, p))), 1);
      valueq = fp_add(fp_mul(e, ONE), mul_q40(logm, INV_LN2));

      if (fp_eq(valueq, 0)) begin
        y = 16'h0000;
      end else begin
        absq = (valueq[63] ? (-valueq) : valueq);
        normq = absq;
        bin_exp = 0;
        for (i = 0; i < 8; i = i + 1)
          if (normq >= 64'sd2199023255552) begin
            normq = normq >>> 1;
            bin_exp = bin_exp + 1;
          end
        for (i = 0; i < 40; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded32 = semantic_rne64(normq, 6'd17, 65'sd65535);
        

        rounded = semantic_rne64(rounded32, 6'd13, 65'sd4095);
        
        out_exp = fp_add(fp_mul((fp_add(bin_exp, 14)), 1024), rounded);
        begin
        semantic_packed_magnitude = out_exp;
        y = fp_add(fp_mul(valueq[63], 16'd32768), semantic_packed_magnitude);
      end
      end
    end
  end
endmodule

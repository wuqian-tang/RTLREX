// FP16 2^x, DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// structural fixed-point 2^x: integer/fraction reduction and Q40 exponential
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
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd549755813888;

  reg signed [63:0] xq, rq, r, eq, normq, rounded32, rounded, rem;
  reg signed [63:0] k, bin_exp, out_exp;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = semantic_multiply128(a, b);
      mul_q40 = product / 128'sd1099511627776;
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
    y = 16'h3c00;
    xq = 0; rq = 0; r = 0; eq = 0; normq = 0;
    rounded32 = 0; rounded = 0; rem = 0;
    k = 0; bin_exp = 0; out_exp = 0;

    if (fp_eq(input_field_14_10, 5'h1f)) begin
      if (fp_ne(input_field_9_0, 0))
        y = 16'h7e00;
      else if (input_field_15_15)
        y = 16'h0000;
      else
        y = 16'h7c00;
    end else if (fp_eq(input_field_14_10, 0)) begin
      y = 16'h3c00;
    end else if (fp_ge(input_field_14_10, 5'd20)) begin
      y = fp_mux(input_field_15_15, 16'h0000, 16'h7c00);
    end else begin
      xq = fp_asl(($signed(fp_add(64'd1024, input_field_9_0))), (fp_add(input_field_14_10, 6'd15)));
      xq = fp_mux(input_field_15_15, fp_sub(0, xq), xq);

      k = fp_add(xq, fp_mux(fp_ge(xq, 0), HALF, fp_sub(0, HALF)));
      k = semantic_asr65(fp_add(k, fp_mux(fp_ge(k, 0), 0, 64'sd1099511627775)), 40);
      rq = fp_sub(xq, fp_mul(k, ONE));
      r = mul_q40(rq, LN2);

      eq = 64'sd1527099483;
      eq = fp_add(64'sd9162596898, mul_q40(eq, r));
      eq = fp_add(64'sd45812984491, mul_q40(eq, r));
      eq = fp_add(64'sd183251937963, mul_q40(eq, r));
      eq = fp_add(64'sd549755813888, mul_q40(eq, r));
      eq = fp_add(64'sd1099511627776, mul_q40(eq, r));
      eq = fp_add(64'sd1099511627776, mul_q40(eq, r));

      normq = fp_mux(fp_ge(eq, ONE), eq, fp_asl(eq, 1));
      bin_exp = fp_mux(fp_ge(eq, ONE), k, fp_sub(k, 1));

      rounded32 = semantic_rne64(normq, 6'd17, 65'sd65535);
      

      out_exp = fp_add(bin_exp, 15);
      if (fp_lt(out_exp, 0))
        y = 16'h0000;
      else if (fp_eq(out_exp, 0)) begin
        rounded = semantic_rne64(rounded32, 6'd14, 65'sd8191);
        y = fp_mux((fp_ge(rounded, 1024)), 16'h0400, 16'h0000);
      end else begin
        rounded = semantic_rne64(rounded32, 6'd13, 65'sd4095);
        out_exp = fp_add(fp_mul((fp_sub(out_exp, 1)), 1024), rounded);
        if (fp_ge(out_exp, 31744))
          y = 16'h7c00;
        else
          y = out_exp;
      end
    end
  end
endmodule

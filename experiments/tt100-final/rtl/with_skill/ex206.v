// BF16 sin(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// 256-bit Payne-Hanek reduction; Q56 degree-9 sine and degree-10 cosine
module top(input [15:0] x, output reg [15:0] y);
  wire input_sign = x[15];
  wire [7:0] input_exponent = x[14:7];
  wire [6:0] input_fraction = x;
  localparam [255:0] TWO_OVER_PI =
    256'ha2f9836e4e441529fc2757d1f534ddc0db6295993c439041fe5163abdebbc561;
  localparam signed [63:0] ONE = 64'sd72057594037927936;
  localparam signed [63:0] PI_OVER_2 = 64'sd113187804032455044;

  reg [263:0] prod;
  reg [63:0] phase_nearest_integer, phase_scaled_product;
  reg [1:0] quadrant;
  
  reg signed [63:0] fracq, r, t, sp, cp, sinv, cosv, valueq;
  reg signed [63:0] absq, normq, bin_exp, out_exp;
  reg signed [63:0] rounded32, rounded, rem;
  integer shift_amt, phase_half_shift, phase_fraction_shift;
  integer i;

  function signed [63:0] mul_q56;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product128;
    begin
      product128 = semantic_multiply128(a, b);
      mul_q56 = product128 / 128'sd72057594037927936;
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
      extended = semantic_add65(extended, value[shift]);
      semantic_rne64 = extended >>> shift;
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
  function signed [63:0] fp_mul;
    input signed [63:0] a, b;
    begin fp_mul = semantic_multiply128(a, b); end
  endfunction
  function signed [64:0] semantic_add65;
    input signed [64:0] a, b;
    begin semantic_add65 = a + b; end
  endfunction

  function signed [127:0] semantic_multiply128;
    input signed [63:0] a, b;
    begin semantic_multiply128 = a * b; end
  endfunction

  function signed [63:0] periodic_select64;
    input signed [63:0] condition;
    input signed [63:0] a, b;
    begin periodic_select64 = condition ? a : b; end
  endfunction

  always @(*) begin
    semantic_packed_magnitude = 0;
    y = 16'h0000;
    prod = 0; phase_nearest_integer = 0; phase_scaled_product = 0;    
    quadrant = 0;  fracq = 0; r = 0; t = 0;
    sp = 0; cp = 0; sinv = 0; cosv = 0; valueq = 0;
    absq = 0; normq = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0; shift_amt = 0; phase_half_shift = 0; phase_fraction_shift = 0;

    if (input_exponent == 8'hff) begin
      y = 16'h7fc0;
    end else if (input_exponent == 0) begin
      y = {input_sign, 15'd0};
    end else if (input_exponent <= 8'd122) begin
      y = x;
    end else begin
      prod = {1'b1, input_fraction} * TWO_OVER_PI;
      shift_amt = fp_add(390, (-input_exponent));
      phase_half_shift = fp_add(shift_amt, (-1));
      phase_fraction_shift = fp_add(shift_amt, (-56));
      phase_nearest_integer = (prod + (265'd1 << phase_half_shift)) >> shift_amt;
      quadrant = phase_nearest_integer;
      phase_scaled_product = prod >> phase_fraction_shift;
      fracq = fp_add(phase_scaled_product, (-(phase_nearest_integer << 56)));
      r = mul_q56(fracq, PI_OVER_2);
      t = mul_q56(r, r);

      sp = 64'sd198571412142;
      sp = fp_add((-64'sd14297141674192), mul_q56(t, sp));
      sp = fp_add(64'sd600479950316066, mul_q56(t, sp));
      sp = fp_add((-64'sd12009599006321323), mul_q56(t, sp));
      sinv = mul_q56(r, fp_add(ONE, mul_q56(t, sp)));

      cp = (-64'sd19857141214);
      cp = fp_add(64'sd1787142709274, mul_q56(t, cp));
      cp = fp_add((-64'sd100079991719344), mul_q56(t, cp));
      cp = fp_add(64'sd3002399751580331, mul_q56(t, cp));
      cp = fp_add((-64'sd36028797018963968), mul_q56(t, cp));
      cosv = fp_add(ONE, mul_q56(t, cp));

      valueq = periodic_select64(quadrant[0], cosv, sinv);
      valueq = periodic_select64(quadrant[1], (-valueq), valueq);
      valueq = periodic_select64(input_sign, (-valueq), valueq);

      
        absq = periodic_select64(valueq[63], (-valueq), valueq);
        normq = absq;
        bin_exp = 0;
        for (i = 0; i < 60; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded32 = semantic_rne64(normq, 6'd33, 65'sd4294967295);
        

        rounded = semantic_rne64(rounded32, 6'd16, 65'sd32767);
        
        out_exp = fp_add(fp_mul((fp_add(bin_exp, 126)), 128), rounded);
        begin
        semantic_packed_magnitude = periodic_select64(fp_eq(valueq, 0), 0, out_exp);
        y = fp_add(fp_mul(periodic_select64(fp_eq(valueq, 0), input_sign, valueq[63]), 16'd32768), semantic_packed_magnitude);
      end
      
    end
  end
endmodule

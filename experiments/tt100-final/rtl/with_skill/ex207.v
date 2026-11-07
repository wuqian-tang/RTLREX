// BF16 tan(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
// Payne-Hanek reduction, Q56 degree-7/8 kernels, normalized tan/cot ratio
module top(input [15:0] x, output reg [15:0] y);
  wire [7:0] input_field_14_7 = x[14:7];
  wire input_field_15_15 = x[15];
  localparam [255:0] TWO_OVER_PI =
    256'ha2f9836e4e441529fc2757d1f534ddc0db6295993c439041fe5163abdebbc561;
  localparam signed [63:0] ONE = 64'sd72057594037927936;
  localparam signed [63:0] PI_OVER_2 = 64'sd113187804032455044;

  reg [263:0] prod;
  reg [63:0] phase_nearest_integer, phase_scaled_product;
  reg [1:0] quadrant;
  reg result_sign;
  reg signed [63:0] fracq, r, t, sp, cp, sinv, cosv;
  reg signed [63:0] num, den, norm_num, norm_den, normq;
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded, rem;
  integer shift_amt;
  integer i;

  function signed [63:0] mul_q56;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product128;
    begin
      product128 = a * b;
      mul_q56 = product128 / 128'sd72057594037927936;
    end
  endfunction

  function signed [63:0] div_q56;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator128;
    begin
      numerator128 = a * 64'sd72057594037927936;
      div_q56 = numerator128 / b;
    end
  endfunction

  reg [14:0] semantic_packed_magnitude;
  function signed [63:0] semantic_rne64;
    input signed [63:0] value;
    input [5:0] shift;
    input signed [64:0] bias;
    reg signed [64:0] extended;
    begin
      extended = value;
      extended = extended + bias;
      extended = extended + value[shift];
      semantic_rne64 = extended >>> shift;
    end
  endfunction

  always @(*) begin
    semantic_packed_magnitude = 0;
    y = 16'h0000;
    prod = 0; phase_nearest_integer = 0; phase_scaled_product = 0;
    quadrant = 0; result_sign = 0;
    fracq = 0; r = 0; t = 0; sp = 0; cp = 0; sinv = 0; cosv = 0;
    num = 0; den = 0; norm_num = 0; norm_den = 0; normq = 0;
    bin_exp = 0; out_exp = 0; rounded32 = 0; rounded = 0; rem = 0;
    shift_amt = 0;

    if (input_field_14_7 == 8'hff) begin
      y = 16'h7fc0;
    end else if (input_field_14_7 == 0) begin
      y = {input_field_15_15, 15'd0};
    end else if (input_field_14_7 <= 8'd122) begin
      y = x;
    end else begin
      prod = {1'b1, x[6:0]} * TWO_OVER_PI;
      shift_amt = 390 - input_field_14_7;
      phase_nearest_integer = (prod + (265'd1 << (shift_amt - 1))) >> shift_amt;
      quadrant = phase_nearest_integer;
      phase_scaled_product = prod >> (shift_amt - 56);
      fracq = phase_scaled_product - (phase_nearest_integer << 56);
      r = mul_q56(fracq, PI_OVER_2);
      t = mul_q56(r, r);

      sp = -64'sd14297141674192;
      sp = 64'sd600479950316066 + mul_q56(t, sp);
      sp = -64'sd12009599006321323 + mul_q56(t, sp);
      sinv = mul_q56(r, ONE + mul_q56(t, sp));

      cp = 64'sd1787142709274;
      cp = -64'sd100079991719344 + mul_q56(t, cp);
      cp = 64'sd3002399751580331 + mul_q56(t, cp);
      cp = -64'sd36028797018963968 + mul_q56(t, cp);
      cosv = ONE + mul_q56(t, cp);

      if (!quadrant[0]) begin
        num = sinv[63] ? -sinv : sinv;
        den = cosv;
        result_sign = sinv[63] ^ input_field_15_15;
      end else begin
        num = cosv;
        den = sinv[63] ? -sinv : sinv;
        result_sign = (sinv[63] == input_field_15_15);
      end

      if (num == 0) begin
        y = {result_sign, 15'd0};
      end else begin
        norm_num = num;
        norm_den = den;
        bin_exp = 0;
        for (i = 0; i < 60; i = i + 1) begin
          if (norm_num >= (norm_den <<< 1)) begin
            norm_den = norm_den <<< 1;
            bin_exp = bin_exp + 1;
          end else if (norm_num < norm_den) begin
            norm_num = norm_num <<< 1;
            bin_exp = bin_exp - 1;
          end
        end
        normq = div_q56(norm_num, norm_den);

        rounded32 = semantic_rne64(normq, 6'd33, 65'sd4294967295);
        rounded = semantic_rne64(rounded32, 6'd16, 65'sd32767);
        out_exp = (bin_exp + 126) * 128 + rounded;
        semantic_packed_magnitude = out_exp;
        y = {result_sign, semantic_packed_magnitude};
      end
    end
  end
endmodule

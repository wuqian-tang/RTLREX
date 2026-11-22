// FP16 sin(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Q40 pi/2 range reduction, polynomial quadrants, FP32 then FP16 RNE
module top(input [15:0] x, output reg [15:0] y);
  wire [4:0] input_field_14_10 = x[14:10];
  wire input_field_15_15 = x[15];
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] PIO2 = 64'sd1727108826179;
  localparam signed [63:0] PI4  = 64'sd863554413089;

  reg signed [63:0] aq, n, r, z, p, sq, cq, vq, magq, normq;
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded;
  reg result_sign;
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

  reg [14:0] semantic_packed_magnitude;
  function signed [63:0] fp_add;
    input signed [63:0] a, b;
    begin fp_add = a + b; end
  endfunction
  function signed [63:0] fp_asr;
    input signed [63:0] a, b;
    begin fp_asr = a >>> b; end
  endfunction
  function fp_eq;
    input signed [63:0] a, b;
    begin fp_eq = a == b; end
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
  function signed [127:0] semantic_multiply128;
    input signed [63:0] a, b;
    begin semantic_multiply128 = a * b; end
  endfunction

  always @(*) begin
    semantic_packed_magnitude = 0;
    y = 16'h0000;
    aq = 0; n = 0; r = 0; z = 0; p = 0; sq = 0; cq = 0;
    vq = 0; magq = 0; normq = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; result_sign = 0;

    if (fp_eq(input_field_14_10, 5'h1f)) begin
      y = 16'h7e00;
    end else if (fp_eq(input_field_14_10, 0)) begin
      y = {input_field_15_15,15'd0};
    end else begin
      aq = (($signed(fp_add(64'd1024, x[9:0]))) <<< (fp_add({1'b0,input_field_14_10}, 15)));
      n = ((fp_add(aq, PI4)) / PIO2);
      r = fp_sub(aq, fp_mul(n, PIO2));
      z = mul_q40(r, r);

      p = 64'sd3029959;
      p = fp_add((-64'sd218157069), mul_q40(p, z));
      p = fp_add(64'sd9162596898, mul_q40(p, z));
      p = fp_add((-64'sd183251937963), mul_q40(p, z));
      sq = fp_add(r, mul_q40(mul_q40(r, z), p));

      p = 64'sd27269634;
      p = fp_add((-64'sd1527099483), mul_q40(p, z));
      p = fp_add(64'sd45812984491, mul_q40(p, z));
      p = fp_add((-64'sd549755813888), mul_q40(p, z));
      cq = fp_add(ONE, mul_q40(z, p));

      if (n[0])
        vq = cq;
      else
        vq = sq;
      if (n[1])
        vq = fp_sub(0, vq);

      result_sign = fp_ne(input_field_15_15, vq[63]);
      if (vq[63])
        magq = fp_sub(0, vq);
      else
        magq = vq;
      normq = magq;
      bin_exp = 0;
      for (i = 0; i < 48; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end

      rounded32 = fp_asr(normq, 17);
      rounded32 = fp_asr((fp_add(fp_add(normq, 64'sd65535), rounded32[0])), 17);
      

      rounded = fp_asr(rounded32, 13);
      rounded = fp_asr((fp_add(fp_add(rounded32, 64'sd4095), rounded[0])), 13);
      

      out_exp = fp_add(fp_mul((fp_add(bin_exp, 14)), 1024), rounded);
      if (fp_lt(out_exp, 1024))
        y = {result_sign,15'd0};
      else
        begin
        semantic_packed_magnitude = out_exp;
        y = fp_add(fp_mul(result_sign, 16'd32768), semantic_packed_magnitude);
      end
    end
  end
endmodule

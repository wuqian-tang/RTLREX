// FP16 tan(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Q40 pi/2 reduction and cubic-over-cubic rational tangent
module top(input [15:0] x, output reg [15:0] y);
  wire [4:0] input_field_14_10 = x[14:10];
  wire input_field_15_15 = x[15];
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] TWO  = 64'sd2199023255552;
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
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 128'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

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
  function fp_ge;
    input signed [63:0] a, b;
    begin fp_ge = fp_le(b, a); end
  endfunction
  function fp_le;
    input signed [63:0] a, b;
    begin fp_le = a <= b; end
  endfunction
  function fp_ne;
    input signed [63:0] a, b;
    begin fp_ne = a != b; end
  endfunction
  function signed [63:0] fp_sub;
    input signed [63:0] a, b;
    begin fp_sub = fp_add(a, -b); end
  endfunction
  always @(*) begin
    y = 16'h0000;
    aq = 0; n = 0; r = 0; z = 0; p = 0; sq = 0; cq = 0;
    vq = 0; magq = 0; normq = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; result_sign = 0;

    if (fp_eq(input_field_14_10, 5'h1f)) begin
      y = 16'h7e00;
    end else if (fp_eq(input_field_14_10, 0)) begin
      y[15] = input_field_15_15;
    end else begin
      aq = ((fp_add(64'sd1024, x[9:0])) <<< (fp_add(input_field_14_10, 15)));
      n = ((fp_add(aq, PI4)) / PIO2);
      r = fp_sub(aq, (n * PIO2));
      z = mul_q40(r, r);

      p = (-64'sd1099511627776);
      p = fp_add(64'sd415615395299328, mul_q40(p, z));
      p = fp_add((-64'sd19049038951219200), mul_q40(p, z));
      sq = fp_add(64'sd148582503819509760, mul_q40(p, z));

      p = (-64'sd30786325577728);
      p = fp_add(64'sd3463461627494400, mul_q40(p, z));
      p = fp_add((-64'sd68576540224389120), mul_q40(p, z));
      cq = fp_add(64'sd148582503819509760, mul_q40(p, z));

      vq = mul_q40(r, div_q40(sq, cq));
      if (n[0])
        vq = fp_sub(0, div_q40(ONE, vq));

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
      for (i = 0; i < 24; i = i + 1)
        if (normq >= TWO) begin
          normq = normq >>> 1;
          bin_exp = bin_exp + 1;
        end

      rounded32 = fp_asr(normq, 17);
      rounded32 = fp_asr((fp_add(fp_add(normq, 64'sd65535), rounded32[0])), 17);
      rounded = fp_asr(rounded32, 13);
      rounded = fp_asr((fp_add(fp_add(rounded32, 64'sd4095), rounded[0])), 13);
      out_exp = fp_add(fp_add(bin_exp, 15), rounded[11]);
      if (fp_le(out_exp, 0)) begin
        y[15] = result_sign;
      end else if (fp_ge(out_exp, 31)) begin
        y = 16'h7c00;
        y[15] = result_sign;
      end else begin
        y[15] = result_sign;
        y[14:10] = out_exp[4:0];
        y[9:0] = rounded[9:0];
      end
    end
  end
endmodule

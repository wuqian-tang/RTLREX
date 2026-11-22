// FP16 1/(1+exp(-x)), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// structural FP16 logistic sigmoid: FP32 exp/add/div then FP16 RNE
module top(input [15:0] x, output reg [15:0] y);
  wire [14:0] input_field_14_0 = x;
  wire [4:0] input_field_14_10 = x[14:10];
  wire input_field_15_15 = x[15];
  localparam signed [63:0] ONE    = 64'sd1099511627776;
  localparam signed [63:0] TWO    = 64'sd2199023255552;
  localparam signed [63:0] LN2    = 64'sd762123384786;
  localparam signed [63:0] HLN2   = 64'sd381061692393;
  localparam signed [63:0] PLIMIT = 64'sd9148280340480;
  localparam signed [63:0] NLIMIT = 64'sd10677288697856;

  reg signed [63:0] aq, k, r, eq, dq, vq, normq, limitq;
  reg signed [63:0] bin_exp, out_exp, rounded;
  reg [9:0] frac;
  reg [4:0] xe;
  reg xs;
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

  function signed [63:0] exp_q40;
    input signed [63:0] a;
    reg signed [63:0] p;
    begin
      p = 64'sd1527099483;
      p = 64'sd9162596898    + mul_q40(p, a);
      p = 64'sd45812984491   + mul_q40(p, a);
      p = 64'sd183251937963  + mul_q40(p, a);
      p = 64'sd549755813888  + mul_q40(p, a);
      p = 64'sd1099511627776 + mul_q40(p, a);
      exp_q40 = 64'sd1099511627776 + mul_q40(p, a);
    end
  endfunction

  function signed [63:0] f32_q40;
    input signed [63:0] a;
    reg signed [63:0] n, e, m;
    integer j;
    begin
      n = a;
      e = 0;
      for (j = 0; j < 48; j = j + 1)
        if (n < ONE) begin
          n = n <<< 1;
          e = e - 1;
        end
      for (j = 0; j < 32; j = j + 1)
        if (n >= TWO) begin
          n = n >>> 1;
          e = e + 1;
        end
      m = n >>> 17;
      m = (n + 64'sd65535 + m[0]) >>> 17;
      f32_q40 = m <<< (e + 17);
    end
  endfunction

  function [15:0] saturation;
    input s;
    begin
      if (s)
        saturation = 16'h0000;
      else
        saturation = 16'h3c00;
    end
  endfunction

  wire activation_tiny = input_field_14_0 <= (input_field_15_15 ? 15'h1000 : 15'h1400);
  wire activation_saturated = input_field_14_0 >= (input_field_15_15 ? 15'h48db : 15'h4829);
  wire [15:0] kernel_x = (activation_tiny || activation_saturated) ? 16'h3c00 : x;

  function signed [63:0] fp_add;
    input signed [63:0] a, b;
    begin fp_add = a + b; end
  endfunction
  function signed [63:0] fp_asl;
    input signed [63:0] a, b;
    begin fp_asl = a <<< b; end
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
  function signed [63:0] fp_sub;
    input signed [63:0] a, b;
    begin fp_sub = fp_add(a, -b); end
  endfunction
  always @(*) begin
    y = 16'h3800;
    frac = x[9:0];
    xe = input_field_14_10;
    xs = input_field_15_15;
    aq = 0; k = 0; r = 0; eq = 0; dq = 0; vq = 0; normq = 0; limitq = 0;
    bin_exp = 0; out_exp = 0; rounded = 0;

    if (fp_eq(xe, 5'h1f)) begin
      if (fp_eq(frac, 0))
        y = saturation(xs);
      else
        y = 16'h7e00;
 end else if (activation_tiny) begin
      y = 16'h3800;
    end else if (activation_saturated) begin
      y = input_field_15_15 ? 16'h0000 : 16'h3c00;
    end else begin
      aq = fp_asl((fp_add(64'sd1024, kernel_x[9:0])), (fp_add(kernel_x[14:10], 15)));
      limitq = (kernel_x[15] ? NLIMIT : PLIMIT);
      if (fp_ge(aq, limitq)) begin
        y = saturation(xs);
      end else begin
        k = ((fp_add(aq, HLN2)) / LN2);
        r = fp_sub(aq, (k * LN2));
        if (kernel_x[15])
          eq = fp_asl(exp_q40(r), k);
        else
          eq = fp_asr(exp_q40(fp_sub(0, r)), k);
        eq = f32_q40(eq);
        dq = f32_q40(fp_add(ONE, eq));
        vq = div_q40(ONE, dq);
        vq = f32_q40(vq);

        normq = vq;
        bin_exp = 0;
        for (i = 0; i < 48; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded = fp_asr(normq, 30);
        rounded = fp_asr((fp_add(fp_add(normq, 64'sd536870911), rounded[0])), 30);
        out_exp = fp_add((fp_add(bin_exp, 14) * 1024), rounded);
        y[14:0] = out_exp;
      end
    end
  end
endmodule

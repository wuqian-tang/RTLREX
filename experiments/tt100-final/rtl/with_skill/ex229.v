// FP16 tanh(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Q40 exp(2|x|) rational reconstruction with signed-one saturation
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE   = 64'sd1099511627776;
  localparam signed [63:0] LN2   = 64'sd762123384786;
  localparam signed [63:0] HLN2  = 64'sd381061692393;
  localparam signed [63:0] LIMIT = 64'sd4956392259584;

  reg signed [63:0] aq, u, k, r, ep, vq, normq;
  reg signed [63:0] bin_exp, out_exp, rounded;
  reg [9:0] frac;
  reg [4:0] xe;
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
    begin fp_ge = a >= b; end
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
    y[15] = x[15];
    frac = x[9:0];
    xe = x[14:10];
    aq = 0; u = 0; k = 0; r = 0; ep = 0; vq = 0; normq = 0;
    bin_exp = 0; out_exp = 0; rounded = 0;

    if (fp_eq(xe, 5'h1f)) begin
      if (fp_eq(frac, 0))
        y[14:0] = 15'h3c00;
      else
        y = 16'h7e00;
    end else if (fp_ne(xe, 0)) begin
      aq = fp_asl((fp_add(64'sd1024, frac)), (fp_add(xe, 15)));
      if (fp_ge(aq, LIMIT)) begin
        y[14:0] = 15'h3c00;
      end else begin
        u = fp_asl(aq, 1);
        k = ((fp_add(u, HLN2)) / LN2);
        r = fp_sub(u, (k * LN2));
        ep = fp_asl(exp_q40(r), k);
        vq = div_q40(fp_sub(ep, ONE), fp_add(ep, ONE));

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

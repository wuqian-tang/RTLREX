// FP16 sinh(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Q40 ln2 reduction and shared degree-7 exp for sinh reconstruction
module top(input [15:0] x, output reg [15:0] y);
  wire [14:0] mag = x[14:0];
  wire [4:0] exponent = x[14:10];
  wire sign = x[15];
  localparam signed [63:0] ONE   = 64'sd1099511627776;
  localparam signed [63:0] TWO   = 64'sd2199023255552;
  localparam signed [63:0] LN2   = 64'sd762123384786;
  localparam signed [63:0] HLN2  = 64'sd381061692393;
  localparam signed [63:0] LIMIT = 64'sd12962211299328;

  reg signed [63:0] aq, k, r, ep, em, vq, normq;
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded;
  reg [9:0] frac;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] exp_q40;
    input signed [63:0] a;
    reg signed [63:0] p;
    begin
      p = 64'sd218157069;
      p = 64'sd1527099483    + mul_q40(p, a);
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
    begin fp_ge = fp_le(b, a); end
  endfunction
  function fp_gt;
    input signed [63:0] a, b;
    begin fp_gt = a > b; end
  endfunction
  function fp_land;
    input signed [63:0] a, b;
    begin fp_land = a && b; end
  endfunction
  function fp_le;
    input signed [63:0] a, b;
    begin fp_le = a <= b; end
  endfunction
  function fp_lor;
    input signed [63:0] a, b;
    begin fp_lor = a || b; end
  endfunction
  function fp_ne;
    input signed [63:0] a, b;
    begin fp_ne = a != b; end
  endfunction
  function signed [63:0] fp_sub;
    input signed [63:0] a, b;
    begin fp_sub = fp_add(a, -b); end
  endfunction

  wire identity_region = fp_land(fp_ge(mag, 15'h400), fp_le(mag, 15'h29c4));
  wire saturation_region = fp_land(fp_ge(mag, 15'h49e5), fp_le(mag, 15'h7bff));
  wire kernel_edge = fp_lor(fp_lor(identity_region, saturation_region),
                            fp_lor(fp_eq(exponent, 0), fp_eq(exponent, 5'h1f)));
  wire [15:0] kernel_x = kernel_edge ? 16'h3c00 : x;

  always @(*) begin
    y = 16'h0000;
    y[15] = sign;
    frac = x[9:0];
    aq = 0; k = 0; r = 0; ep = 0; em = 0; vq = 0; normq = 0;
    bin_exp = 0; out_exp = 0; rounded32 = 0; rounded = 0;

    if (fp_eq(exponent, 5'h1f)) begin
      if (fp_eq(frac, 0))
        y[14:0] = 15'h7c00;
      else
        y = 16'h7e00;
    end else if (identity_region) begin
      y = x;
    end else if (saturation_region) begin
      y = {sign, 15'h7c00};
    end else if (fp_ne(exponent, 0)) begin
      aq = fp_asl(fp_add(64'sd1024, kernel_x[9:0]),
                  fp_add(kernel_x[14:10], 15));
      if (fp_ge(aq, LIMIT)) begin
        y[14:0] = 15'h7c00;
      end else begin
        k = fp_add(aq, HLN2) / LN2;
        r = fp_sub(aq, k * LN2);
        ep = fp_asl(exp_q40(r), k);
        em = fp_asr(exp_q40(fp_sub(0, r)), k);
        vq = fp_asr(fp_sub(ep, em), 1);

        normq = vq;
        bin_exp = 0;
        repeat (48)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end
        repeat (24)
          if (normq >= TWO) begin
            normq = normq >>> 1;
            bin_exp = bin_exp + 1;
          end

        rounded32 = fp_asr(normq, 17);
        rounded32 = fp_asr(fp_add(fp_add(normq, 64'sd65535), rounded32[0]), 17);
        rounded = fp_asr(rounded32, 13);
        rounded = fp_asr(fp_add(fp_add(rounded32, 64'sd4095), rounded[0]), 13);
        out_exp = fp_add(fp_add(bin_exp, 15), rounded[11]);
        if (fp_gt(out_exp, 0)) begin
          y[14:10] = out_exp[4:0];
          y[9:0] = rounded[9:0];
        end
      end
    end
  end
endmodule

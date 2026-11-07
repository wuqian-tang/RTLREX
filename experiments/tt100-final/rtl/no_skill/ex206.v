module top(input [15:0] x, output reg [15:0] y);
  // bfloat16 sine.  Input subnormals are flushed to signed zero.
  reg [154:0] product;
  reg [7:0] exponent;
  reg [27:0] phase;
  reg [26:0] fraction;
  reg sine_negative;
  reg signed [29:0] angle, square, accumulator, magnitude, bias;
  reg [8:0] rounded;
  integer shift, lead, i;

  function signed [29:0] mul_fixed;
    input signed [29:0] a;
    input signed [29:0] b;
    reg signed [59:0] full;
    begin
      full = a * b;
      mul_fixed = full >>> 27;
    end
  endfunction

  always @* begin
    y = 0;
    product = 0;
    exponent = x[14:7];
    phase = 0;
    fraction = 0;
    sine_negative = 0;
    angle = 0;
    square = 0;
    accumulator = 0;
    magnitude = 0;
    bias = 0;
    rounded = 0;
    shift = 0;
    lead = 0;

    if (exponent == 0) begin
      y = x;
      y[14:0] = 0;
    end else if (exponent == 8'hff) begin
      y = 16'h7fc0;
    end else if (exponent <= 122) begin
      y = x;
    end else begin
      // 147 fractional bits of 1/pi retain the half-turn for all bfloat16s.
      product = (128 + x[6:0]) *
                147'h28be60db9391054a7f09d5f47d4d377036d8a;
      shift = 254 - exponent;
      phase = product >> shift;
      fraction = phase;
      sine_negative = phase[27];
      if (fraction[26]) begin
        angle = 30'sd134217728 - fraction;
      end else begin
        angle = fraction;
      end

      // Convert the residual half-turn to radians (Q27), then approximate
      // sin on [-pi/2, pi/2].
      angle = mul_fixed(angle, 30'sd421657428);
      square = mul_fixed(angle, angle);
      accumulator = -30'sd4;
      accumulator = 30'sd370 + mul_fixed(accumulator, square);
      accumulator = -30'sd26631 + mul_fixed(accumulator, square);
      accumulator = 30'sd1118481 + mul_fixed(accumulator, square);
      accumulator = -30'sd22369622 + mul_fixed(accumulator, square);
      accumulator = 30'sd134217728 + mul_fixed(accumulator, square);
      magnitude = mul_fixed(angle, accumulator);

      // Normalize and round the Q27 magnitude to bfloat16, ties to even.
      for (i = 0; i <= 27; i = i + 1)
        if (magnitude[i]) lead = i;
      shift = lead - 7;
      bias = (30'sd1 << (shift-1)) - 1 + magnitude[shift];
      rounded = (magnitude + bias) >> shift;
      y = ((lead + 99) << 7) + rounded;
      y[15] = x[15] != sine_negative;
    end
  end
endmodule

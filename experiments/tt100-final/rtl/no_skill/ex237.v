module top(input [15:0] x, output [15:0] y);
  // Recovered binary16 cube root.  Subnormals are flushed to signed zero;
  // infinities retain their sign and NaNs become the canonical 16'h7e00.
  reg [15:0] result;
  reg [14:0] magnitude;
  reg [4:0] exponent, quotient;
  reg [9:0] fraction;
  reg [1:0] remainder;
  reg [12:0] low, step, candidate;
  reg [36:0] scaled;
  reg [37:0] cube;

  always @(x) begin
    exponent = x[14:10];
    fraction = x;
    result = x;
    magnitude = x;

    if (exponent == 31) begin
      if (fraction) begin
        result = 0;
        magnitude = 15'h7e00;
      end
    end else if (exponent) begin
      remainder = exponent % 3;
      quotient = exponent / 3;
      scaled = 1024 + fraction;
      scaled = scaled << (23 + remainder);
      // Preserve the source's binary32-to-binary16 midpoint rounding case.
      scaled = scaled - 1024;

      // Search the odd, doubled midpoint (2*significand - 1).
      low = 2047;
      step = 2048;
      repeat (11) begin
        candidate = low + step;
        cube = candidate ** 3;
        if (cube <= scaled)
          low = candidate;
        step = step >> 1;
      end

      magnitude = (quotient * 2048 + low + 18433) >> 1;
    end else
      magnitude = 0;
    result[14:0] = magnitude;
  end

  assign y = result;
endmodule

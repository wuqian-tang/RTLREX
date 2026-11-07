module top(input [15:0] x, output reg [15:0] y);
  integer exponent, significand, square, numerator, rounded, upper_half, encoded;
  always @(x) begin
    exponent = x[14:7];
    significand = 128 + x[6:0];
    y = 0;
    // Canonical NaN; the sign of the bfloat16 input is immaterial.
    if (x[14:0] > 16'h7f80) y = 16'h7fc0;
    else begin
      upper_half = significand > 181;
      square = significand * significand;
      numerator = 4194304 << upper_half;
      // Round the reciprocal-square significand to nearest.
      rounded = (numerator + square/2) / square;
      encoded = (379 - 2*exponent - upper_half)*128 + rounded;
      if (encoded >= 32640) y = 16'h7f80;
      else if (encoded > 127) y = encoded;
    end
  end
endmodule

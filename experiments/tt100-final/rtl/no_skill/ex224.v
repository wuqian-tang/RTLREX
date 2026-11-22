module top(input [15:0] x, output reg [15:0] y);
  reg [63:0] q, q2, term, sum, product, fraction;
  reg signed [63:0] exponent_value, logarithm;
  integer i;

  function [15:0] to_half;
    input signed [63:0] value;
    reg [63:0] magnitude, rounded, halfway;
    reg sign_bit;
    integer bit_position, shift, half_exponent, k;
    begin
      if (value == 0) begin
        to_half = 16'b0;
      end else begin
        sign_bit = value[63];
        magnitude = sign_bit ? -value : value;
        bit_position = 0;
        for (k = 0; k < 64; k = k + 1)
          if (magnitude[k]) bit_position = k;
        shift = bit_position - 10;
        rounded = magnitude >> shift;
        halfway = 64'b1 << (shift - 1);
        // Round to nearest, resolving an exact tie toward an even significand.
        rounded = (magnitude + halfway - 1 + rounded[0]) >> shift;
        half_exponent = bit_position - 17 + rounded[11];
        to_half = {sign_bit, half_exponent[4:0], rounded[9:0]};
      end
    end
  endfunction

  always @(x) begin
    q = 0;
    q2 = 0;
    term = 0;
    sum = 0;
    product = 0;
    fraction = 0;
    exponent_value = 0;
    logarithm = 0;
    if (x[14:10] == 0) begin
      // This implementation flushes binary16 subnormals to signed zero.
      y = 16'hfc00;
    end else if (x[15]) begin
      y = 16'h7e00;
    end else if (x[14:10] == 31) begin
      y = (x[9:0] == 0) ? 16'h7c00 : 16'h7e00;
    end else begin
      // log2(1+f) = 2/ln(2) * (q + q^3/3 + ...), q=f/(2+f).
      q = (x[9:0] * 64'd4294967296) / (2048 + x[9:0]);
      q2 = (q * q) >> 32;
      term = q;
      sum = q;
      for (i = 3; i <= 13; i = i + 2) begin
        term = (term * q2) >> 32;
        sum = sum + term / i;
      end
      product = sum * 64'd6196328019;
      fraction = product >> 31;
      exponent_value = x[14:10] - 64'sd15;
      logarithm = (exponent_value <<< 32) + $signed(fraction);
      y = to_half(logarithm);
    end
  end
endmodule

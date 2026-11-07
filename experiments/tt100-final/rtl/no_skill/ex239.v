// Binary16 reciprocal cube root, rounded to nearest.  Input subnormals are
// treated as signed zero; NaNs are mapped to the canonical quiet NaN.
module top(input [15:0] x, output reg [15:0] y);
  wire sign = x[15];
  wire [4:0] exponent = x[14:10];
  wire [9:0] fraction = x;
  wire exceptional = exponent == 5'h1f;

  reg [10:0] mantissa;
  reg [11:0] root, trial, bit_value;
  reg [12:0] midpoint;
  reg [63:0] target, product;
  always @(x) begin
    if (exceptional && fraction)
      y = 16'h7e00;                    // canonical NaN
    else begin
      if (exponent == 0)
        y = 16'h7c00;                  // zero/subnormal -> infinity
      else if (exceptional)
        y = 0;                         // infinity -> signed zero
      else begin
        mantissa = 1024 + fraction;
        // Eight times the radicand, for exact half-way comparisons.
        target = 64'h400000000000 >> (exponent%3);
        root = 1024;
        bit_value = 1024;
        // Compare each candidate against the exact cubed rounding boundary.
        repeat (11) begin
          trial = root + bit_value;
          midpoint = (trial << 1) - 1;
          product = midpoint;
          product = product ** 3 * mantissa;
          if (product < target)
            root = trial;
          bit_value = bit_value >> 1;
        end
        y = ((18-exponent/3) << 10) + root;
      end
      y[15] = sign;
    end
  end
endmodule

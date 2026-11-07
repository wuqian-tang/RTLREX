// bfloat16 y = x**-3, round-to-nearest-even, with DAZ/FTZ handling.
module top(input [15:0] x, output reg [15:0] y);
  reg [7:0] mant;
  reg [7:0] input_exponent;
  reg [23:0] cube;
  reg [31:0] numerator;
  reg [7:0] significand;
  integer shift, exponent;

  always @(*) begin
    mant = {1'b1, x[6:0]};
    input_exponent = x[14:7];
    cube = mant ** 3;
    shift = cube <= 24'd2097152 ? 0 :
            cube <= 24'd4194304 ? 1 :
            cube <= 24'd8388608 ? 2 : 3;
    numerator = 32'h10000000 << shift;
    // A half-way case is impossible here: numerator is a power of two,
    // while the only power-of-two cube (128^3) divides it exactly.
    significand = (numerator + (cube >> 1)) / cube;

    exponent = 508 - 3 * input_exponent - shift;
    // Canonical NaN; otherwise saturate overflow and flush underflow.
    y = {
      ((input_exponent == 8'hff) && x[6:0]) ? 1'b0 : x[15],
      ((input_exponent == 8'hff) && x[6:0]) ? 8'hff :
        (exponent >= 255) ? 8'hff : (exponent > 0) ? exponent[7:0] : 8'b0,
      ((input_exponent == 8'hff) && x[6:0]) ? 7'h40 :
        ((exponent > 0) && (exponent < 255)) ? significand[6:0] : 7'b0
    };
  end
endmodule

// FP8 E5M2 multiply, RNE, canonical NaN, finite saturation, signed zero
// Word arithmetic; normalized integer encoding with exact ties-to-even rounding.
module top(input [15:0] x, output reg [7:0] y);
  wire [6:0] a = x[14:8], b = x[6:0];
  function [32:0] magnitude;
    input [6:0] v;
    reg [4:0] exponent;
    reg [1:0] fraction;
    reg normal;
    begin
      exponent = v[6:2];
      fraction = v;
      normal = exponent != 0;
      magnitude = {normal, fraction} << (exponent - normal);
    end
  endfunction
  wire [32:0] ma = magnitude(a), mb = magnitude(b);
  function [6:0] encode;
    input [65:0] value;
    reg [66:0] rounded;
    integer j, shift, exponent, code;
    begin
      shift = 16;
      for (j = 19; j < 66; j = j + 1)
        if (value[j]) shift = j - 2;
      exponent = shift - 16;
      rounded = (value + ((67'd1 << shift) >> 1) -
                 !value[shift]) >> shift;
      code = (exponent << 2) + rounded;
      encode = code > 126 ? 7'd126 : code;
    end
  endfunction
  wire sa = x[15], sb = x[7];
  wire [65:0] product = ma * mb;
  wire [6:0] result = encode(product);
  always @(*) begin
    if ((a == 127) || (b == 127)) y = 8'h7f;
    else y = {(sa != sb), result};
  end
endmodule

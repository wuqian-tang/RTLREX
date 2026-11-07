// FP8 E4M3FN multiply, RNE, canonical NaN, finite saturation, signed zero
// Word arithmetic; normalized integer encoding with exact ties-to-even rounding.
module top(input [15:0] x, output reg [7:0] y);
  wire [6:0] a = x[14:8], b = x[6:0];
  function [17:0] magnitude;
    input [6:0] v;
    reg [3:0] exponent;
    reg [2:0] fraction;
    reg normal;
    begin
      exponent = v[6:3];
      fraction = v;
      normal = exponent != 0;
      magnitude = {normal, fraction} << (exponent - normal);
    end
  endfunction
  wire [17:0] ma = magnitude(a), mb = magnitude(b);
  function [6:0] encode;
    input [35:0] value;
    reg [36:0] rounded;
    integer j, shift, exponent, code;
    begin
      shift = 9;
      for (j = 13; j < 36; j = j + 1)
        if (value[j]) shift = j - 3;
      exponent = shift - 9;
      rounded = (value + ((37'd1 << shift) >> 1) -
                 (shift && !value[shift])) >> shift;
      code = (exponent << 3) + rounded;
      encode = code > 126 ? 7'd126 : code;
    end
  endfunction
  wire sa = x[15], sb = x[7];
  wire [35:0] product = ma * mb;
  wire [6:0] result = encode(product);
  always @(*) begin
    if ((a == 127) || (b == 127)) y = 8'h7f;
    else y = {(sa != sb), result};
  end
endmodule

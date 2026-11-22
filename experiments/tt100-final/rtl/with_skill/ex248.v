// FP8 E5M2 fmod(x[7:0], x[15:8]), trunc-toward-zero quotient, RNE
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
    input [34:0] value;
    reg [35:0] rounded;
    integer j, shift, exponent, code;
    begin
      shift = 0;
      for (j = 3; j < 35; j = j + 1)
        if (value[j]) shift = j - 2;
      exponent = shift;
      rounded = (value + ((36'd1 << shift) >> 1) -
                 (shift && !value[shift])) >> shift;
      code = (exponent << 2) + rounded;
      encode = code > 126 ? 7'd126 : code;
    end
  endfunction
  wire sb = x[7];
  wire [34:0] remainder = mb % ma;
  wire [6:0] result = encode(remainder);
  always @(*) begin
    if ((a == 127) || (b == 127) || (ma == 0)) y = 8'h7f;
    else y = {sb, result};
  end
endmodule

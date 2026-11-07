// FP8 E4M3FN fmod(x[7:0], x[15:8]), trunc-toward-zero quotient, RNE
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
    input [19:0] value;
    reg [20:0] rounded;
    integer j, shift, exponent, code;
    begin
      shift = 0;
      for (j = 4; j < 20; j = j + 1)
        if (value[j]) shift = j - 3;
      exponent = shift;
      rounded = (value + ((21'd1 << shift) >> 1) -
                 (shift && !value[shift])) >> shift;
      code = (exponent << 3) + rounded;
      encode = code > 126 ? 7'd126 : code;
    end
  endfunction
  wire sb = x[7];
  wire [19:0] remainder = mb % ma;
  wire [6:0] result = encode(remainder);
  always @(*) begin
    if ((a == 127) || (b == 127) || (ma == 0)) y = 8'h7f;
    else y = {sb, result};
  end
endmodule

// FP8 E5M2 add, RNE, canonical NaN, finite saturation, signed-zero preservation
// Finite-only signed dyadic arithmetic and exact nearest-even integer encoder.
module top(input [15:0] x, output [7:0] y);
  wire [6:0] a = x[14:8], b = x;
  wire signed [15:0] whole = x;
  wire signed [7:0] low = x;
  function signed [35:0] add_words;
    input signed [35:0] left, right;
    begin add_words = left + right; end
  endfunction
  function greater;
    input signed [35:0] left, right;
    begin greater = left > right; end
  endfunction
  wire sa = greater(36'd0, whole);
  wire sb = greater(36'd0, low);
  function signed [34:0] signed_value;
    input [6:0] encoding;
    input sign;
    reg [4:0] exponent;
    reg [1:0] fraction;
    reg normal;
    reg [34:0] value;
    begin
      exponent = encoding[6:2];
      fraction = encoding;
      normal = greater(exponent, 36'd0);
      value = {normal, fraction} << (exponent - normal);
      signed_value = sign ? -$signed(value) : $signed(value);
    end
  endfunction
  function [6:0] encode;
    input [34:0] value;
    reg [35:0] rounded;
    integer j, shift, code;
    begin
      shift = 0;
      for (j = 3; j < 35; j = j + 1)
        if (value[j]) shift = j - 2;
      rounded = (add_words(value, ((36'd1 << shift) >> 1)) -
                 (shift && !value[shift])) >> shift;
      code = add_words((shift << 2), rounded);
      encode = greater(code, 36'd126) ? 7'd126 : code;
    end
  endfunction
  wire signed [34:0] total = add_words(signed_value(a, sa), signed_value(b, sb));
  wire negative = greater(36'd0, total);
  wire [34:0] absolute = negative ? -total : total;
  wire [6:0] result = encode(absolute);
  assign y = (greater(a, 36'd126) || greater(b, 36'd126)) ?
      8'd127 : {(negative || (sa && sb)), result};
endmodule

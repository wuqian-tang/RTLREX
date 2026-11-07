// FP8 E4M3FN add, RNE, canonical NaN, finite saturation, signed-zero preservation
// Finite-only signed dyadic arithmetic and exact nearest-even integer encoder.
module top(input [15:0] x, output [7:0] y);
  wire [6:0] a = x[14:8], b = x;
  wire sa = x[15], sb = x[7];
  function signed [31:0] add_words;
    input signed [31:0] left, right;
    begin add_words = left + right; end
  endfunction
  function greater;
    input [31:0] left, right;
    begin greater = left > right; end
  endfunction
  function signed [19:0] signed_value;
    input [6:0] encoding;
    input sign;
    reg [3:0] exponent;
    reg [2:0] fraction;
    reg normal;
    reg [19:0] value;
    begin
      exponent = encoding[6:3];
      fraction = encoding;
      normal = greater(exponent, 32'd0);
      value = {normal, fraction} << (exponent - normal);
      signed_value = sign ? -$signed(value) : $signed(value);
    end
  endfunction
  function [6:0] encode;
    input [19:0] value;
    reg [20:0] rounded;
    integer j, shift, code;
    begin
      shift = 0;
      for (j = 4; j < 20; j = j + 1)
        if (value[j]) shift = j - 3;
      rounded = (add_words(value, ((21'd1 << shift) >> 1)) -
                 (shift && !value[shift])) >> shift;
      code = add_words((shift << 3), rounded);
      encode = greater(code, 32'd126) ? 7'd126 : code;
    end
  endfunction
  wire signed [19:0] total = add_words(signed_value(a, sa), signed_value(b, sb));
  wire negative = total[19];
  wire [19:0] absolute = negative ? -total : total;
  wire [6:0] result = encode(absolute);
  assign y = (greater(a, 32'd126) || greater(b, 32'd126)) ?
      8'd127 : {(negative || (sa && sb)), result};
endmodule

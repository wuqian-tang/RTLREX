// two-lane packed FP4 E2M1 dot product to FP8 E4M3, fused exact sum, RNE
// Finite lane decoding, exact integer product sum and dyadic ties-to-even.
module top(input [15:0] x, output [7:0] y);
  function signed [31:0] word_add;
    input signed [31:0] a, b;
    begin word_add = a + b; end
  endfunction
  function [3:0] lane;
    input [15:0] word;
    input [1:0] index;
    begin lane = word >> (index * 4); end
  endfunction
  function negative;
    input [3:0] value;
    begin negative = value >= 4'd8; end
  endfunction
  function signed [4:0] decode;
    input [3:0] value;
    reg [1:0] exponent;
    reg [0:0] fraction;
    reg signed [4:0] magnitude;
    begin
      exponent = value >> 1;
      fraction = value;
      magnitude = exponent ? word_add(2, fraction) << (exponent - 1) : fraction;
      decode = negative(value) ? -magnitude : magnitude;
    end
  endfunction
  function [6:0] encode;
    input [9:0] value;
    integer leading, bit_index, shift;
    reg [10:0] rounded;
    begin
      encode = 0;
      leading = 0;
      shift = 0;
      rounded = 0;
      if (value) begin
        for (bit_index = 0; bit_index < 10; bit_index = bit_index + 1)
          if (value[bit_index]) leading = bit_index;
        shift = leading - 3;
        if (shift > 0)
          rounded = word_add(value, (word_add((11'd1 << shift) - 1, value[shift]) >> 1)) >> shift;
        else
          rounded = value << -shift;
        encode = word_add(word_add(leading, 4) << 3, rounded);
      end
    end
  endfunction
  reg [3:0] left_lane, right_lane;
  reg signed [8:0] product;
  reg signed [9:0] total;
  reg all_negative;
  integer index;
  always @(*) begin
    total = 0;
    product = 0;
    left_lane = 0;
    right_lane = 0;
    all_negative = 1;
    for (index = 0; index < 2; index = index + 1) begin
      left_lane = lane(x, index);
      right_lane = lane(x, index + 2);
      product = decode(left_lane) * decode(right_lane);
      total = total + product;
      all_negative = all_negative && (negative(left_lane) != negative(right_lane));
    end
  end
  wire is_negative = total < 0;
  wire [9:0] absolute_total = is_negative ? -total : total;
  assign y = {(total ? is_negative : all_negative), encode(absolute_total)};
endmodule

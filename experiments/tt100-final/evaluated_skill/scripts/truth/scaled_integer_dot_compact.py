"""Exact bounded unsigned fixed-point dots with finite floating-point outputs.

All parameters describe a mathematical format. The emitter rejects contracts
requiring subnormal output or saturation rather than silently dropping either.
"""
from fractions import Fraction


def emit_unsigned_scaled_dot(lane_bits: int, fractional_bits: int, lanes: int,
                             detail: str, output_exponent_bits: int = 4,
                             output_fraction_bits: int = 3) -> str:
    """Fuse a dot of two unsigned packed vectors and round once, ties to even.

    Input lanes encode integer / 2**fractional_bits. The low packed lanes are
    the first vector; the high packed lanes are the second. All nonzero exact
    sums must fit the normal finite output range, whose last magnitude is NaN.
    Widths follow exact product and sum bounds, including contextual multiply.
    """
    arguments = (lane_bits, fractional_bits, lanes, output_exponent_bits,
                 output_fraction_bits)
    if any(type(value) is not int for value in arguments):
        raise ValueError('format widths and lane count must be integers')
    if not (1 <= lane_bits <= 8 and 0 <= fractional_bits <= lane_bits and
            1 <= lanes <= 8 and 2 <= output_exponent_bits <= 5 and
            1 <= output_fraction_bits <= 5):
        raise ValueError('unsupported unsigned scaled dot format')
    product_bound = ((1 << lane_bits) - 1) ** 2
    total_bound = lanes * product_bound
    output_bias = (1 << (output_exponent_bits - 1)) - 1
    smallest = Fraction(2) ** (-2 * fractional_bits)
    largest = total_bound * smallest
    output_minimum = Fraction(2) ** (1 - output_bias)
    output_maximum = ((1 << (output_fraction_bits + 1)) - 2) * Fraction(2) ** (
        (1 << output_exponent_bits) - 1 - output_bias - output_fraction_bits)
    if smallest < output_minimum or largest > output_maximum:
        raise ValueError('dot range requires subnormal or saturation handling')
    product_width = product_bound.bit_length()
    total_width = total_bound.bit_length()
    input_width = 2 * lane_bits * lanes
    index_width = max(1, (2 * lanes - 1).bit_length())
    output_width = 1 + output_exponent_bits + output_fraction_bits
    magnitude_width = output_width - 1
    rounded_width = max(total_width + 1, output_fraction_bits + 2)
    add_width = max(32, rounded_width)
    offset = output_bias - 1 - 2 * fractional_bits
    return f'''// {detail}
// Exact unsigned integer product sum and dyadic ties-to-even encoding.
module top(input [{input_width-1}:0] x, output [{output_width-1}:0] y);
  function signed [{add_width-1}:0] word_add;
    input signed [{add_width-1}:0] a, b;
    begin word_add = a + b; end
  endfunction
  function [{lane_bits-1}:0] lane;
    input [{input_width-1}:0] word;
    input [{index_width-1}:0] index;
    begin lane = word >> (index * {lane_bits}); end
  endfunction
  function [{magnitude_width-1}:0] encode;
    input [{total_width-1}:0] value;
    integer leading, bit_index, shift;
    reg [{rounded_width-1}:0] rounded;
    begin
      encode = 0;
      leading = 0;
      shift = 0;
      rounded = 0;
      if (value) begin
        for (bit_index = 0; bit_index < {total_width}; bit_index = bit_index + 1)
          if (value[bit_index]) leading = bit_index;
        shift = leading - {output_fraction_bits};
        if (shift > 0)
          rounded = word_add(value, (word_add(({total_width+1}'d1 << shift) - 1, value[shift]) >> 1)) >> shift;
        else
          rounded = value << -shift;
        encode = word_add(word_add(leading, {offset}) << {output_fraction_bits}, rounded);
      end
    end
  endfunction
  reg [{product_width-1}:0] product;
  reg [{total_width-1}:0] total;
  integer index;
  always @(*) begin
    total = 0;
    product = 0;
    for (index = 0; index < {lanes}; index = index + 1) begin
      product = lane(x, index) * lane(x, index + {lanes});
      total = total + product;
    end
  end
  assign y = encode(total);
endmodule
'''

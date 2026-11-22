"""Transparent integer arithmetic for finite packed floating-point reductions.

The admitted dot contracts have finite input encodings and an output range
containing every reachable nonzero product sum as a normal finite value.
Parameters describe the mathematical format and lane count, not a case name.
"""
from fractions import Fraction


def _power2(exponent: int) -> Fraction:
    return Fraction(2) ** exponent


def emit_finite_float_dot(exponent_bits: int, fraction_bits: int, lanes: int,
                          detail: str, output_exponent_bits: int = 4,
                          output_fraction_bits: int = 3) -> str:
    """Emit an exact fused dot of two packed finite binary-format vectors.

    The low lanes form one vector, the high lanes the other. All exponent
    encodings are finite. A reserved all-ones output magnitude is canonical
    NaN, though this finite bounded dot cannot produce it. IEEE addition of
    zero products retains negative zero iff every product has negative sign.
    Unsupported range contracts fail closed instead of dropping FTZ/clamps.
    """
    arguments = (exponent_bits, fraction_bits, lanes,
                 output_exponent_bits, output_fraction_bits)
    if any(type(value) is not int for value in arguments):
        raise ValueError('format widths and lane count must be integers')
    if not (1 <= exponent_bits <= 4 and 0 <= fraction_bits <= 5 and
            1 <= lanes <= 4 and 2 <= output_exponent_bits <= 5 and
            1 <= output_fraction_bits <= 5):
        raise ValueError('unsupported finite packed dot format')
    width = 1 + exponent_bits + fraction_bits
    if width > 8:
        raise ValueError('input lane is wider than the bounded finite format')
    bias = (1 << (exponent_bits - 1)) - 1
    unit_exponent = 1 - bias - fraction_bits
    largest = ((1 << (fraction_bits + 1)) - 1) << ((1 << exponent_bits) - 2)
    product_bound = largest * largest
    total_bound = lanes * product_bound
    output_bias = (1 << (output_exponent_bits - 1)) - 1
    minimum = _power2(2 * unit_exponent)
    maximum = total_bound * minimum
    output_minimum = _power2(1 - output_bias)
    output_maximum = ((1 << (output_fraction_bits + 1)) - 2) * _power2(
        (1 << output_exponent_bits) - 1 - output_bias - output_fraction_bits)
    if minimum < output_minimum or maximum > output_maximum:
        raise ValueError('dot range requires subnormal or saturation handling')
    decoded_width = largest.bit_length() + 1
    product_width = product_bound.bit_length() + 1
    total_width = total_bound.bit_length() + 1
    input_width = 2 * lanes * width
    index_width = max(1, (2 * lanes - 1).bit_length())
    magnitude_width = output_exponent_bits + output_fraction_bits
    output_width = magnitude_width + 1
    offset = output_bias - 1 + 2 * unit_exponent
    rounded_width = max(total_width + 1, output_fraction_bits + 2)
    add_width = max(32, rounded_width)
    return f'''// {detail}
// Finite lane decoding, exact integer product sum and dyadic ties-to-even.
module top(input [{input_width-1}:0] x, output [{output_width-1}:0] y);
  function signed [{add_width-1}:0] word_add;
    input signed [{add_width-1}:0] a, b;
    begin word_add = a + b; end
  endfunction
  function [{width-1}:0] lane;
    input [{input_width-1}:0] word;
    input [{index_width-1}:0] index;
    begin lane = word >> (index * {width}); end
  endfunction
  function negative;
    input [{width-1}:0] value;
    begin negative = value >= {width}'d{1 << (width-1)}; end
  endfunction
  function signed [{decoded_width-1}:0] decode;
    input [{width-1}:0] value;
    reg [{exponent_bits-1}:0] exponent;
    reg [{max(1, fraction_bits)-1}:0] fraction;
    reg signed [{decoded_width-1}:0] magnitude;
    begin
      exponent = value >> {fraction_bits};
      fraction = {'value' if fraction_bits else "1'b0"};
      magnitude = exponent ? word_add({1 << fraction_bits}, fraction) << (exponent - 1) : fraction;
      decode = negative(value) ? -magnitude : magnitude;
    end
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
  reg [{width-1}:0] left_lane, right_lane;
  reg signed [{product_width-1}:0] product;
  reg signed [{total_width-1}:0] total;
  reg all_negative;
  integer index;
  always @(*) begin
    total = 0;
    product = 0;
    left_lane = 0;
    right_lane = 0;
    all_negative = 1;
    for (index = 0; index < {lanes}; index = index + 1) begin
      left_lane = lane(x, index);
      right_lane = lane(x, index + {lanes});
      product = decode(left_lane) * decode(right_lane);
      total = total + product;
      all_negative = all_negative && (negative(left_lane) != negative(right_lane));
    end
  end
  wire is_negative = total < 0;
  wire [{total_width-1}:0] absolute_total = is_negative ? -total : total;
  assign y = {{(total ? is_negative : all_negative), encode(absolute_total)}};
endmodule
'''

"""Exact integer cube with proved, format-wide rounding simplifications.

No truth-address dispatch: all flags follow from the complete admitted binary
format. The emitted circuit still computes a power, normalizes, rounds and
packs it arithmetically. DAZ, FTZ, signed zero and canonical NaN are retained.
"""
from functools import lru_cache


def rne_shift(value: int, shift: int) -> int:
    if shift <= 0:
        return value << -shift
    return (value + (1 << (shift - 1)) - 1 + ((value >> shift) & 1)) >> shift


def round_binary(value: int, power: int, e: int, f: int):
    """Round an exact nonnegative dyadic to binary e/f, retaining subnormals.

    Return None for infinity, otherwise (integer coefficient, binary power).
    This is independent of the emitter's exponent packing and midpoint tests.
    """
    if value == 0:
        return (0, 0)
    bias = (1 << (e - 1)) - 1
    top = value.bit_length() - 1 + power
    quantum = max(top - f, 1 - bias - f)
    coefficient = rne_shift(value, quantum - power)
    if coefficient.bit_length() - 1 + quantum > bias:
        return None
    return coefficient, quantum


def encode_ftz(value, e: int, f: int) -> int:
    """Pack an independently rounded dyadic, flushing output subnormals."""
    scale = 1 << f
    maximum = (1 << e) - 1
    if value is None:
        return maximum * scale
    coefficient, power = value
    if coefficient == 0:
        return 0
    bias = (1 << (e - 1)) - 1
    top = coefficient.bit_length() - 1 + power
    if top < 1 - bias:
        return 0
    # A rounding carry may leave f+2 bits. Exact normalization is wiring.
    mantissa = coefficient << max(0, f + 1 - coefficient.bit_length())
    mantissa >>= max(0, coefficient.bit_length() - f - 1)
    return ((top + bias) << f) + mantissa - scale


def cube_oracle(bits: int, e: int, f: int, intermediate=True) -> int:
    """DAZ input, optional true binary32 RNE, target RNE+FTZ cube oracle."""
    scale, maximum = 1 << f, (1 << e) - 1
    sign = (bits >> (e + f)) << (e + f)
    exp, fraction = (bits >> f) & maximum, bits & (scale - 1)
    infinity = maximum * scale
    if exp == maximum:
        return infinity + scale // 2 if fraction else sign + infinity
    if exp == 0:
        return sign
    bias = (1 << (e - 1)) - 1
    product = (scale + fraction) ** 3
    power = 3 * (exp - bias - f)
    if intermediate:
        staged = round_binary(product, power, 8, 23)
        result = None if staged is None else round_binary(*staged, e, f)
    else:
        result = round_binary(product, power, e, f)
    return sign + encode_ftz(result, e, f)


@lru_cache(maxsize=64)
def format_properties(e: int, f: int) -> dict:
    """Complete finite-format proofs; the result controls source algebra only.

    Intermediate-removal proof includes every normal exponent, so true binary32
    subnormal rounding and overflow are covered, in addition to significands.
    Bounded supported dimensions keep construction time and memory predictable.
    """
    if type(e) is not int or type(f) is not int or not (3 <= e <= 8 and 1 <= f <= 10):
        raise ValueError('supported cube format requires 3<=e<=8 and 1<=f<=10')
    scale, maximum, bias = 1 << f, (1 << e) - 1, (1 << (e-1)) - 1
    carry_free = half_up_exact = promotion_none = promotion_code_exact = True
    for sig in range(scale, 2 * scale):
        product = sig ** 3
        norm = product.bit_length() - 1 - 3 * f
        shift = 2 * f + norm
        rounded = rne_shift(product, shift)
        carry_free &= rounded < 2 * scale
        half_up_exact &= rounded == (product + (1 << (shift-1))) >> shift
        # expOut=0 is reachable iff this residue yields a normal input exponent.
        if (2*bias-norm) % 3 == 0 and 1 <= (2*bias-norm)//3 < maximum:
            promotion = product >= ((2*scale-1) << shift)
            promotion_none &= not promotion
            promotion_code_exact &= promotion == (rounded == 2*scale-1)
    mismatches = 0
    first_mismatch = None
    for exp in range(1, maximum):
        for fraction in range(scale):
            bits = exp * scale + fraction
            if cube_oracle(bits, e, f, True) != cube_oracle(bits, e, f, False):
                mismatches += 1
                if first_mismatch is None:
                    first_mismatch = bits
    return dict(exponent_bits=e, fraction_bits=f, normal_positive_inputs=(maximum-1)*scale,
                significands=scale, carry_free=bool(carry_free),
                half_up_exact=bool(half_up_exact), promotion_none=bool(promotion_none),
                promotion_code_exact=bool(promotion_code_exact),
                binary32_stage_removable=mismatches == 0,
                stage_mismatches=mismatches, first_stage_mismatch=first_mismatch)


def emit_binary_cube(e: int, f: int, detail: str = 'DAZ/FTZ binary cube') -> str:
    props = format_properties(e, f)
    if not props['binary32_stage_removable']:
        raise ValueError('format needs explicit binary32 intermediate rounding')
    if not props['carry_free']:
        raise ValueError('format needs explicit rounding carry support')
    if not (props['promotion_none'] or props['promotion_code_exact']):
        raise ValueError('format needs explicit FTZ promotion threshold')
    width, scale, bias = 1+e+f, 1 << f, (1 << (e-1))-1
    maximum, product_width, exponent_width = (1 << e)-1, 3*(f+1), e+3
    rounding = f"(product + ({product_width+1}'d{1 << (2*f-1)} << normalize)) >> rounding_shift"
    if not props['half_up_exact']:
        rounding = f"(product + ({product_width+1}'d{1 << (2*f-1)} << normalize) - 1 + product[rounding_shift]) >> rounding_shift"
    underflow = '0' if props['promotion_none'] else f"code == {scale-1} ? {e+f}'d{scale} : 0"
    return f'''// {detail}
// Format-wide proofs permit direct exact-cube rounding and carry-free packing.
module top(input [{width-1}:0] x, output reg [{width-1}:0] y);
  wire sign_in = x[{width-1}];
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{f-1}:0] fraction = x;
  wire [{e+f-1}:0] input_magnitude = x;
  wire [{f}:0] significand = {f+1}'d{scale} + fraction;
  wire [{product_width-1}:0] product = significand ** 3;
  wire [1:0] normalize = product[{3*f+2}] ? 2'd2 : product[{3*f+1}];
  wire signed [2:0] positive_normalize = normalize;
  wire [7:0] rounding_shift = {2*f} + normalize;
  wire [{f}:0] rounded = {rounding};
  wire [{f-1}:0] rounded_fraction = rounded;
  wire signed [{exponent_width-1}:0] positive_exponent = exponent;
  wire signed [{exponent_width-1}:0] output_exponent = 3 * positive_exponent - {2*bias} + positive_normalize;
  wire signed [{exponent_width+f-1}:0] code = {{output_exponent, rounded_fraction}};
  reg [{e+f-1}:0] magnitude;
  always @(*) begin
    if (code >= {maximum*scale}) magnitude = {e+f}'d{maximum*scale};
    else if (code < {scale}) magnitude = {underflow};
    else magnitude = code;
    y = {{sign_in, magnitude}};
    if (input_magnitude > {maximum*scale}) y = {width}'d{maximum*scale+scale//2};
  end
endmodule
'''

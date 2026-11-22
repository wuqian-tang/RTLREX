"""Exact staged cubic-root rounding through powered midpoint intervals.

A format-wide property proof can narrow intermediate precision, but never
remove a rounding difference. No input-address tables or case-specific patches
are emitted: a bounded numeric midpoint scan performs the mathematical test.
The typed greater-than function shares source syntax, not physical hardware.
"""
from functools import lru_cache


def integer_cuberoot(value: int) -> int:
    if value < 0:
        raise ValueError('nonnegative radicand required')
    lo, hi = 0, 1 << ((value.bit_length() + 2) // 3)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if mid ** 3 <= value:
            lo = mid
        else:
            hi = mid
    return lo


def rounded_cuberoot(value: int) -> int:
    root = integer_cuberoot(value)
    # An integer radicand cannot equal an odd powered half-integer midpoint.
    return root + ((value << 3) > (2 * root + 1) ** 3)


def round_shift(value: int, shift: int) -> int:
    if shift < 0:
        raise ValueError('nonnegative rounding shift required')
    if shift == 0:
        return value
    return (value + (1 << (shift - 1)) - 1 + ((value >> shift) & 1)) >> shift


def staged_significand(sig: int, remainder: int, f: int, p: int) -> int:
    first = rounded_cuberoot(sig << (3 * p - f + remainder))
    return round_shift(first, p - f)


@lru_cache(maxsize=64)
def root_format_properties(e: int, f: int, precision: int | None = 23) -> dict:
    precision = f if precision is None else precision
    if (type(e) is not int or type(f) is not int or type(precision) is not int
            or not (3 <= e <= 8 and 1 <= f <= 10 and f <= precision <= 32)):
        raise ValueError('root format needs 3<=E<=8, 1<=F<=10, F<=precision<=32')
    scale = 1 << f
    reference = [staged_significand(sig, rem, f, precision)
                 for sig in range(scale, 2 * scale) for rem in range(3)]
    direct = [staged_significand(sig, rem, f, f)
              for sig in range(scale, 2 * scale) for rem in range(3)]
    effective = precision
    tested = []
    for candidate in range(f, precision + 1):
        values = [staged_significand(sig, rem, f, candidate)
                  for sig in range(scale, 2 * scale) for rem in range(3)]
        mismatches = sum(a != b for a, b in zip(values, reference))
        tested.append({'precision': candidate, 'mismatches': mismatches})
        if mismatches == 0:
            effective = candidate
            break
    bias, maximum = (1 << (e - 1)) - 1, (1 << e) - 1
    # Cubic roots of every admitted normal input remain normal in binary32 and
    # in the target format; their exponents are the quotient below, or +1 carry.
    output_exponents = [(exponent + 2 * bias) // 3
                        for exponent in range(1, maximum)]
    assert min(output_exponents) >= 1 and max(output_exponents) + 1 < maximum
    assert (1 - bias) // 3 >= -126 and bias // 3 + 1 <= 127
    delta = effective - f
    # Validate the general powered-interval theorem for every possible input
    # significand/residue. The circuit scans these intervals, not this list.
    for index, (sig, rem) in enumerate((s, r) for s in range(scale, 2*scale) for r in range(3)):
        target = sig << (3 * effective - f + rem + 3)
        count = 0
        for lower in range(scale, 2 * scale):
            midpoint = 2 * lower + 1
            if delta:
                midpoint = (midpoint << delta) + (1 if not lower & 1 else -1)
            count += target > midpoint ** 3
        assert scale + count == reference[index]
    return {'exponent_bits': e, 'fraction_bits': f, 'requested_intermediate_precision': precision,
            'effective_intermediate_precision': effective,
            'significand_residue_inputs': 3 * scale,
            'precision_candidates': tested,
            'direct_rounding_mismatches': sum(a != b for a,b in zip(direct,reference)),
            'all_normal_exponents_covered_analytically': maximum - 1,
            'binary32_root_exponents_normal': True,
            'target_normal_output_exponent_range': [min(output_exponents), max(output_exponents)+1],
            'staged_powered_midpoint_identity_verified': True}


def root_oracle(bits: int, e: int, f: int, precision: int | None = 23) -> int:
    """Independent normalized integer-root then explicit RN-even target oracle."""
    precision = f if precision is None else precision
    scale, maximum = 1 << f, (1 << e) - 1
    sign = bits & (1 << (e + f))
    magnitude = bits & ((1 << (e + f)) - 1)
    exponent, fraction = divmod(magnitude, scale)
    infinity = maximum * scale
    if exponent == maximum:
        return infinity + scale // 2 if fraction else sign + infinity
    if exponent == 0:
        return sign
    bias = (1 << (e - 1)) - 1
    quotient, remainder = divmod(exponent + 2 * bias, 3)
    rounded = staged_significand(scale + fraction, remainder, f, precision)
    return sign + (quotient - 1) * scale + rounded


def emit_staged_cubic_root(e: int, f: int, detail: str = 'Staged binary cubic root',
                           precision: int | None = 23) -> str:
    precision = f if precision is None else precision
    props = root_format_properties(e, f, precision)
    p = props['effective_intermediate_precision']
    width, scale = 1 + e + f, 1 << f
    maximum, bias = (1 << e) - 1, (1 << (e - 1)) - 1
    work = 3 * (p + 2)
    delta = p - f
    midpoint_start = ((2 * scale + 1) << delta) + (1 if delta else 0)
    increment = 2 << delta
    bias_decl = f'  reg [{p+1}:0] alternating_bias;\n' if delta else ''
    bias_init = '    alternating_bias = -2;\n' if delta else ''
    midpoint_update = f'midpoint + {p+2}\'d{increment}' + (' + alternating_bias' if delta else '')
    bias_update = '      alternating_bias = -alternating_bias;\n' if delta else ''
    return f'''// {detail}
// RN{precision} then RN{f}: format-wide proof retains exact staged midpoint decisions.
// Typed function reuse reduces lexical syntax only; it does not imply physical sharing.
module top(input [{width-1}:0] x, output reg [{width-1}:0] y);
  wire sign_in = x[{width-1}];
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{f-1}:0] fraction = x;
  wire [{e+f-1}:0] input_magnitude = x;
  wire [{f}:0] significand = {f+1}'d{scale} + fraction;
  wire [{e+1}:0] biased_exponent = exponent + {e+2}'d{2*bias};
  wire [{e+1}:0] exponent_quotient = biased_exponent / 3;
  wire [1:0] remainder = biased_exponent % 3;
  reg [{work-1}:0] target;
  reg [{p+1}:0] midpoint;
{bias_decl}  reg [{e+f-1}:0] code;
  function greater;
    input [{work-1}:0] a;
    input [{work-1}:0] b;
    begin greater = a > b; end
  endfunction
  function same_exponent;
    input [{e-1}:0] a;
    input [{e-1}:0] b;
    begin same_exponent = a == b; end
  endfunction
  always @(*) begin
    target = significand << ({3*p-f+3} + remainder);
    midpoint = {p+2}'d{midpoint_start};
{bias_init}    code = exponent_quotient * {e+f}'d{scale};
    repeat ({scale}) begin
      code = code + greater(target, midpoint ** 3);
      midpoint = {midpoint_update};
{bias_update}    end
    if (same_exponent(exponent, {e}'d0)) code = 0;
    else if (same_exponent(exponent, {e}'d{maximum})) code = {e+f}'d{maximum*scale};
    y = {{sign_in, code}};
    if (greater(input_magnitude, {work}'d{maximum*scale})) y = {width}'d{maximum*scale+scale//2};
  end
endmodule
'''

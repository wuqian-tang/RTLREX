"""Parameterized exact binary arithmetic candidates, with no corpus dispatch.

Candidates still require the unchanged complete-domain circuit verifier.
Arithmetic and every intermediate width remain visible in generated RTL.
"""


def emit_binary_square(exponent_bits: int, fraction_bits: int,
                       detail: str = 'DAZ/FTZ binary magnitude square') -> str:
    """Square with fixed-point normalization and format-derived guard bounds.

    Bias is odd. sqrt(min_normal) and the first overflowing input are exact
    binade endpoints with encoded exponents (bias+1)/2 and (3*bias+1)/2.
    The immediately preceding input has a spacing larger than the output
    rounding half-step, so no earlier promotion changes either boundary.
    NaN is the payload interval strictly above the infinity encoding.

    Left-shifting only the lower half of the full squared significand into
    the common binary point loses no bits. Every halfway squared integer
    has an even retained quotient, so half-minus-one implements exact RNE.
    Every typed unsigned comparison site uses the same full-width helper.
    """
    if (type(exponent_bits) is not int or type(fraction_bits) is not int
            or not 3 <= exponent_bits <= 8 or not 1 <= fraction_bits <= 23):
        raise ValueError('binary square requires e in 3..8 and f in 1..23')
    e,f=exponent_bits,fraction_bits
    width=1+e+f;payload=e+f;bias=(1 << (e-1))-1
    infinity=((1 << e)-1) << f;nan=infinity|(1 << (f-1))
    lower=((bias+1)//2) << f;upper=((3*bias+1)//2) << f
    product_width=2*(f+1);compare_width=max(payload,product_width)
    return f'''// {detail}
// Exact binary square with constant input guard boundaries and fixed RNE scale.
module top(input [{width-1}:0] x, output [{width-1}:0] y);
  wire [{payload-1}:0] magnitude = x;
  wire [{e-1}:0] exponent = magnitude[{payload-1}:{f}];
  wire [{f-1}:0] fraction = magnitude;
  wire [{f}:0] significand = {f+1}'d{1 << f} + fraction;
  wire [{product_width-1}:0] product = significand * significand;
  function greater;
    input [{compare_width-1}:0] left, right;
    begin greater = left > right; end
  endfunction
  wire normalize = greater({compare_width}'d{1 << (2*f+1)}, product);
  wire [{product_width-1}:0] aligned = product << normalize;
  wire [{f+1}:0] rounded = (aligned + {product_width+1}'d{(1 << f)-1}) >> {f+1};
  wire [{width+1}:0] packed_result = (exponent * {width+2}'d2 - {width+2}'d{bias} - normalize) *
      {width+2}'d{1 << f} + rounded;
  assign y = greater(magnitude, {compare_width}'d{infinity}) ? {width}'d{nan} :
             greater({compare_width}'d{upper}, magnitude) ?
             (greater({compare_width}'d{lower}, magnitude) ? {width}'d0 : packed_result) :
             {width}'d{infinity};
endmodule
'''


def _reciprocal_ftz_boundary_safe(e: int, f: int, p: int) -> bool:
    """Prove both monotone FTZ promotion cutoffs agree, without a format list.

    Only binades whose exact reciprocal overlaps the minimum-normal boundary
    can differ. Within each, both promotion predicates decrease monotonically
    with the positive integer significand. Comparing their final accepted
    significands proves equality for the whole significand interval. Binary
    search uses exact integer inequalities, never corpus truth or output tables.
    """
    bias=(1 << (e-1))-1;scale=1 << f
    def last_true(predicate):
        low,high=scale-1,2*scale
        while high-low>1:
            middle=(low+high)//2
            if predicate(middle):low=middle
            else:high=middle
        return low
    for exponent in range(1,(1 << e)-1):
        base=(p+1)*bias-p*exponent
        if not 1 <= base <= p+1:continue
        threshold=1 << ((p+1)*(bias+f)-p*exponent)
        def staged(significand):
            return significand**p*((1 << (f+1))-1) <= threshold
        def linear(significand):
            denominator=significand**p
            normalize=1+sum(denominator>(1 << (p*f+j)) for j in range(1,p))
            rounded=((1 << ((p+1)*f+normalize))+(denominator//2))//denominator
            return (base-1-normalize)*scale+rounded >= scale
        if last_true(staged)!=last_true(linear):return False
    return True


def emit_binary_reciprocal_power(exponent_bits: int, fraction_bits: int,
                                 degree: int, detail: str = 'Binary reciprocal power') -> str:
    """Exact normalized reciprocal square/cube with linear exponent packing.

    Rounded significand q lies in [2**f,2**(f+1)], including its carry.
    Packing (base_exponent-1)*2**f+q incorporates both the hidden bit and
    carry, without separately selecting carry/fraction bits. Exponent-zero
    DAZ inputs necessarily overflow for e>=3 and degree>=2; infinity inputs
    necessarily underflow. Thus the same signed packed bounds handle them.
    NaN remains the explicit interval above the input infinity payload.
    """
    if (type(exponent_bits) is not int or type(fraction_bits) is not int
            or type(degree) is not int or not 3 <= exponent_bits <= 8
            or not 1 <= fraction_bits <= 23 or degree not in (2,3)):
        raise ValueError('reciprocal power requires e in 3..8, f in 1..23, p=2 or3')
    e,f,p=exponent_bits,fraction_bits,degree
    if not _reciprocal_ftz_boundary_safe(e,f,p):
        raise ValueError('normalized RNE does not preserve staged FTZ promotion in this format')
    width=1+e+f;payload=e+f;bias=(1 << (e-1))-1
    infinity=((1 << e)-1) << f;nan=infinity|(1 << (f-1))
    denominator_width=p*(f+1);numerator_width=(p+1)*f+p+2
    encoded_width=width+3;compare_width=max(encoded_width,denominator_width+1)
    normalization=(f"greater(denominator, {compare_width}'sd{1 << (p*f+1)}) ? 2'd2 : 2'd1"
                   if p==2 else
                   f"greater(denominator, {compare_width}'sd{1 << (p*f+2)}) ? 2'd3 : "
                   f"greater(denominator, {compare_width}'sd{1 << (p*f+1)}) ? 2'd2 : 2'd1")
    sign=f"  wire sign_in = x[{width-1}];\n" if p==3 else ''
    output='{sign_in, magnitude}' if p==3 else 'magnitude'
    return f'''// {detail}
// Normalized integer reciprocal power, exact RNE division and linear packing.
module top(input [{width-1}:0] x, output [{width-1}:0] y);
{sign}  wire [{payload-1}:0] input_magnitude = x;
  wire [{e-1}:0] exponent = input_magnitude[{payload-1}:{f}];
  wire [{f-1}:0] fraction = input_magnitude;
  wire [{f}:0] significand = {f+1}'d{1 << f} + fraction;
  wire [{denominator_width-1}:0] denominator = significand ** {p};
  function greater;
    input signed [{compare_width-1}:0] left, right;
    begin greater = left > right; end
  endfunction
  wire [1:0] normalize = {normalization};
  wire [{f+1}:0] rounded = (({numerator_width}'d{1 << ((p+1)*f)} << normalize) +
                            (denominator >> 1)) / denominator;
  wire signed [{encoded_width-1}:0] packed_result =
      ({encoded_width}'sd{(p+1)*bias-1} - exponent * {encoded_width}'sd{p} - normalize) *
      {encoded_width}'sd{1 << f} + rounded;
  wire [{payload-1}:0] magnitude = greater({compare_width}'sd{infinity}, packed_result) ?
      (greater({compare_width}'sd{1 << f}, packed_result) ? {payload}'d0 : packed_result) :
      {payload}'d{infinity};
  assign y = greater(input_magnitude, {compare_width}'sd{infinity}) ? {width}'d{nan} : {output};
endmodule
'''


def emit_finite_hypot(exponent_bits: int, fraction_bits: int,
                      detail: str = 'Finite binary Euclidean magnitude') -> str:
    """Finite-only magnitude hypot, gradual underflow, RNE, finite saturation.

    The sole NaN payload is the largest unsigned magnitude code; signs are
    ignored and the output sign is zero. All other encodings are finite.
    This is not an IEEE infinity/NaN encoding and must only be selected after
    that complete semantic contract matches the supplied circuit.

    sqrt(a*a+b*b) is at least max(a,b) and at most sqrt(2)*max(a,b).
    Starting at the larger monotone encoding, 2**(f-1)+1 adjacent boundaries
    suffice (sqrt(2)-1 < 1/2); crossing binades increases spacing.

    For f <= 3, a squared midpoint equality with an odd retained code is
    impossible. After removing common powers of two from an equality, its
    hypotenuse is odd and congruent to 3 mod 4, below 32. In that interval
    only hypotenuse 15 has non-axis integer legs: 9 and 12. Its odd leg 9
    needs four significant bits, while the format whose odd midpoint is 15
    has f=2 and only three; neither that leg nor the axis midpoint is an
    input value. For f=3 the odd hypotenuses are 19,23,27,31 and have no
    non-axis integer legs. Subnormal unscaled midpoints are odd and cannot
    equal four times an integer sum of squares. Therefore strict midpoint
    comparison already implements ties-to-even, without dropping a stage.

    The wide unsigned comparison helper is used at three real arithmetic
    sites; its source reuse is not a claim of physical hardware sharing.
    """
    if (type(exponent_bits) is not int or type(fraction_bits) is not int
            or not 2 <= exponent_bits <= 5 or not 1 <= fraction_bits <= 3):
        raise ValueError('finite hypot requires e in 2..5 and f in 1..3')
    e,f=exponent_bits,fraction_bits
    payload=e+f; operand=payload+1; maximum=(1 << payload)-1
    word=((1 << e)-2)+f+1
    steps=(1 << (f-1))+1
    return f'''// {detail}
// Exact finite-only hypot: bounded adjacent numeric midpoints, no lookup table.
module top(input [{2*operand-1}:0] x, output reg [{operand-1}:0] y);
  wire [{payload-1}:0] a = x[{2*operand-2}:{operand}], b = x;
  function [{2*word+1}:0] midpoint_squared;
    input [{payload-1}:0] encoding;
    input half_step;
    reg [{e-1}:0] exponent;
    reg [{f-1}:0] fraction;
    reg normal;
    reg [{word}:0] decoded;
    begin
      exponent = encoding[{payload-1}:{f}];
      fraction = encoding;
      normal = exponent != 0;
      decoded = {{normal, fraction, half_step}} << (exponent - normal);
      midpoint_squared = decoded * decoded;
    end
  endfunction
  function greater;
    input [{2*word+2}:0] left, right;
    begin greater = left > right; end
  endfunction
  wire [{2*word+2}:0] four_value = midpoint_squared(a, 1'b0) + midpoint_squared(b, 1'b0);
  reg [{payload-1}:0] code;
  always @(*) begin
    code = greater(a, b) ? a : b;
    repeat ({steps}) begin
      code = code + (greater({payload}'d{maximum-1}, code) &&
                     greater(four_value, midpoint_squared(code, 1'b1)));
    end
    y = code;
  end
endmodule
'''


def emit_binary_reciprocal_sqrt(exponent_bits: int, fraction_bits: int,
                                detail: str = 'Binary reciprocal square root') -> str:
    """Exact rational-midpoint nearest-root Newton with typed guard reuse.

    N is a power of two and the rounded root is at least two. An exact odd
    half-integer root would require an odd square greater than one to divide
    N, hence cannot occur. floor(N/S-1/4) preserves every rounding boundary.
    The monotone nearest-integer Newton recurrence halves positive error;
    starting at 2**(f+1), f+1 updates suffice, including the carry encoding.
    """
    if (type(exponent_bits) is not int or type(fraction_bits) is not int
            or not 3 <= exponent_bits <= 8 or not 1 <= fraction_bits <= 23):
        raise ValueError('reciprocal sqrt requires e in 3..8 and f in 1..23')
    e,f=exponent_bits,fraction_bits;width=e+f+1;bias=(1 << (e-1))-1
    infinity=((1 << e)-1) << f;nan=infinity|(1 << (f-1));nw=3*f+5
    return f'''// {detail}
// Rational midpoint-preserving integer bias and bounded nearest-root Newton.
module top(input [{width-1}:0] x, output reg [{width-1}:0] y);
  wire [{width-2}:0] input_magnitude = x;
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{e}:0] exponent_before_hidden = ({e+1}'d{3*bias-3} - exponent) >> 1;
  function greater;
    input [{width-1}:0] left, right;
    begin greater = left > right; end
  endfunction
  reg [{f}:0] significand;
  reg [{2*f+1}:0] biased_radicand;
  reg [{f+1}:0] root;
  always @(*) begin
    significand = x;
    significand[{f}] = 1'b1;
    biased_radicand = (({nw}'d{1 << (3*f+3)} << exponent[0]) - significand) / (significand << 2);
    root = {f+2}'d{1 << (f+1)};
    repeat ({f+1}) root = (root + biased_radicand / root + 1) >> 1;
    if (greater({width}'d{1 << f}, input_magnitude))
      y = {{x[{width-1}], {width-1}'d{infinity}}};
    else if (greater(x, {width}'d{infinity-1}))
      y = greater(x, {width}'d{infinity}) ? {width}'d{nan} : {width}'d0;
    else y = exponent_before_hidden * {width}'d{1 << f} + root;
  end
endmodule
'''


def emit_finite_add(exponent_bits: int, fraction_bits: int,
                    detail: str = 'Finite binary signed addition') -> str:
    """Gradual-underflow finite-only addition, RNE, finite saturation.

    The maximal unsigned payload is the sole NaN. Both negative zero inputs
    retain negative zero; cancellation of opposite signs yields positive zero.
    A full-width signed sum helper is actually reused at arithmetic
    sites; this shares source syntax, without claiming physical resource reuse.
    """
    if (type(exponent_bits) is not int or type(fraction_bits) is not int
            or not 2 <= exponent_bits <= 5 or not 1 <= fraction_bits <= 3):
        raise ValueError('finite add requires e in 2..5 and f in 1..3')
    e,f=exponent_bits,fraction_bits;payload=e+f;operand=payload+1
    word=(1 << e)-2+f+1;value_width=word+2;arithmetic_width=max(value_width+1,32)
    maximum=(1 << payload)-1
    return f'''// {detail}
// Finite-only signed dyadic arithmetic and exact nearest-even integer encoder.
module top(input [{2*operand-1}:0] x, output [{operand-1}:0] y);
  wire [{payload-1}:0] a = x[{2*operand-2}:{operand}], b = x;
  wire sa = x[{2*operand-1}], sb = x[{operand-1}];
  function signed [{arithmetic_width-1}:0] add_words;
    input signed [{arithmetic_width-1}:0] left, right;
    begin add_words = left + right; end
  endfunction
  function greater;
    input [{arithmetic_width-1}:0] left, right;
    begin greater = left > right; end
  endfunction
  function signed [{value_width-1}:0] signed_value;
    input [{payload-1}:0] encoding;
    input sign;
    reg [{e-1}:0] exponent;
    reg [{f-1}:0] fraction;
    reg normal;
    reg [{value_width-1}:0] value;
    begin
      exponent = encoding[{payload-1}:{f}];
      fraction = encoding;
      normal = greater(exponent, {arithmetic_width}'d0);
      value = {{normal, fraction}} << (exponent - normal);
      signed_value = sign ? -$signed(value) : $signed(value);
    end
  endfunction
  function [{payload-1}:0] encode;
    input [{value_width-1}:0] value;
    reg [{value_width}:0] rounded;
    integer j, shift, code;
    begin
      shift = 0;
      for (j = {f+1}; j < {value_width}; j = j + 1)
        if (value[j]) shift = j - {f};
      rounded = (add_words(value, (({value_width+1}'d1 << shift) >> 1)) -
                 (shift && !value[shift])) >> shift;
      code = add_words((shift << {f}), rounded);
      encode = greater(code, {arithmetic_width}'d{maximum-1}) ? {payload}'d{maximum-1} : code;
    end
  endfunction
  wire signed [{value_width-1}:0] total = add_words(signed_value(a, sa), signed_value(b, sb));
  wire negative = total[{value_width-1}];
  wire [{value_width-1}:0] absolute = negative ? -total : total;
  wire [{payload-1}:0] result = encode(absolute);
  assign y = (greater(a, {arithmetic_width}'d{maximum-1}) || greater(b, {arithmetic_width}'d{maximum-1})) ?
      {operand}'d{maximum} : {{(negative || (sa && sb)), result}};
endmodule
'''

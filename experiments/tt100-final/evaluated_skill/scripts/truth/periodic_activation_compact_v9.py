"""Analytic control compaction for fixed-point periodic/activation kernels.

This module does not inspect a truth table, a filename, or a benchmark identity.
Unsupported source structures are returned unchanged. Every accepted candidate
still requires independent complete-domain validation before use.
"""
from __future__ import annotations

import re


def _typed_helper(rtl: str, name: str, *, input_bits: int = 64,
                  result_bits: int | None = None,
                  expressions: tuple[str, ...]) -> bool:
    """Validate a complete pure helper declaration, including signed ports."""
    definitions = list(re.finditer(r'\bfunction\b.*?\bendfunction\b', rtl, re.S))
    named = [d[0] for d in definitions if re.match(
        r'function\s+(?:signed\s*\[\d+:0\]\s*)?' + re.escape(name) + r'\s*;',d[0])]
    if len(named) != 1:
        return False
    result = '' if result_bits is None else r'signed\s*\['+str(result_bits-1)+r':0\]\s*'
    pattern = (r'function\s+' + result + re.escape(name) + r'\s*;\s*'
               r'input\s+signed\s*\[' + str(input_bits-1) + r':0\]\s*a\s*,\s*b\s*;\s*'
               r'begin\s+' + re.escape(name) + r'\s*=\s*(?P<expression>[^;]+)\s*;\s*end\s*endfunction')
    match = re.fullmatch(pattern,named[0])
    return bool(match and re.sub(r'\s+','',match['expression']) in expressions)


def _comparison_contracts(rtl: str, names: tuple[str, ...]) -> bool:
    meanings = {'fp_eq':('a==b',),'fp_ne':('a!=b',),'fp_le':('a<=b',),
                'fp_ge':('a>=b','fp_le(b,a)'), 'fp_land':('a&&b',)}
    if not all(_typed_helper(rtl,name,expressions=meanings[name]) for name in names):
        return False
    # A reflected comparison is correct only if the callee also satisfies its
    # full signed-64 declaration and meaning.
    if 'fp_ge' in names and re.search(r'fp_ge\s*=\s*fp_le\(b,\s*a\)',rtl):
        return _typed_helper(rtl,'fp_le',expressions=meanings['fp_le'])
    return True


def phase_geometry_safe(*, constant: int, constant_bits: int,
                        fraction_bits: int, exponent_bits: int,
                        reduction_bias: int, phase_bits: int) -> bool:
    """Prove that rounding the reduction quotient cannot encounter a tie.

    A hidden-bit significand has at most ``fraction_bits`` trailing zeros.
    Multiplication by an odd constant preserves that valuation. A midpoint
    remainder has valuation shift-1, hence cannot occur if every admitted
    normal exponent gives shift-1 greater than fraction_bits. The fractional
    output also needs a nonnegative right shift. Special exponents are handled
    by the unchanged surrounding kernel guards.
    """
    minimum_shift = reduction_bias - ((1 << exponent_bits) - 2)
    return (constant_bits >= 2 and 1 <= fraction_bits <= 30
            and 2 <= exponent_bits <= 10 and 1 <= phase_bits < 63
            and 0 < constant < (1 << constant_bits) and constant & 1 == 1
            and minimum_shift > fraction_bits + 1
            and minimum_shift >= phase_bits)


_PHASE = re.compile(
    r'ipart\s*=\s*prod\s*>>\s*shift_amt\s*;\s*'
    r'remainder\s*=\s*prod\s*-\s*\(ipart\s*<<\s*shift_amt\)\s*;\s*'
    r'if\s*\(shift_amt\s*<=\s*(?P<width>\d+)\)\s*begin\s*'
    r'halfv\s*=\s*(?P=width)\x27d1\s*<<\s*\(shift_amt\s*-\s*1\)\s*;\s*'
    r'round_up\s*=\s*\(remainder\s*>\s*halfv\)\s*\|\|\s*'
    r'\(\(remainder\s*==\s*halfv\)\s*&&\s*ipart\[0\]\)\s*;\s*end\s*'
    r'quadrant\s*=\s*ipart\[1:0\]\s*\+\s*round_up\s*;\s*'
    r'frac_wide\s*=\s*remainder\s*>>\s*\(shift_amt\s*-\s*(?P<q>\d+)\)\s*;\s*'
    r'if\s*\(round_up\)\s*fracq\s*=\s*\$signed\(frac_wide\[63:0\]\)\s*-\s*ONE\s*;\s*'
    r'else\s*fracq\s*=\s*\$signed\(frac_wide\[63:0\]\)\s*;')


def compact_periodic_phase(rtl: str, *, exponent_bits: int = 8,
                           fraction_bits: int = 7) -> str:
    """Eliminate dead reduction control without shortening its product.

    q = floor((product + half)/2**shift) is exact because ties are impossible.
    The product-plus-half uses one guard bit: without it, shift=product_width
    can overflow. The signed Q fraction is floor(product/2**(shift-Q))-q*2**Q.
    Cancellation modulo 2**64 is exact since the resulting fraction lies in
    [-2**(Q-1), 2**(Q-1)); it is not a truncated product approximation.
    """
    if '`' in rtl or '/*' in rtl or 'phase_nearest_integer' in rtl:
        return rtl
    code = re.sub(r'//[^\n]*', '', rtl)
    matches = list(_PHASE.finditer(code))
    original_matches = list(_PHASE.finditer(rtl))
    if len(matches) != 1 or len(original_matches) != 1:
        return rtl
    match = original_matches[0]
    constant = re.search(r'localparam\s*\[(\d+):0\]\s*TWO_OVER_PI\s*=\s*'
                         r'(\d+)\x27h([0-9a-fA-F]+)\s*;', code)
    shift = re.search(r'shift_amt\s*=\s*(\d+)\s*-\s*'
                      r'(?P<exp>\w+|x\[\d+:\d+\])\s*;', code)
    one = re.search(r'localparam\s+signed\s*\[63:0\]\s*ONE\s*=\s*64\x27sd(\d+)\s*;', code)
    declaration = re.search(r'reg\s*\[(\d+):0\]\s*prod,\s*ipart,\s*remainder,\s*halfv,\s*frac_wide\s*;', rtl)
    if not constant or not shift or not one or not declaration:
        return rtl
    p = int(constant[1]) + 1
    w = int(match['width'])
    q = int(match['q'])
    if (int(constant[2]) != p or int(declaration[1]) + 1 != w
            or w != p + fraction_bits + 1 or int(one[1]) != 1 << q
            or not phase_geometry_safe(constant=int(constant[3], 16),
                                      constant_bits=p, fraction_bits=fraction_bits,
                                      exponent_bits=exponent_bits,
                                      reduction_bias=int(shift[1]), phase_bits=q)):
        return rtl
    exp = re.escape(shift['exp'])
    # The maximum exponent is never admitted to the normal reduction branch.
    excluded = re.search(r'if\s*\(\s*' + exp + r'\s*==\s*'
                         + str(exponent_bits) + r"'h([0-9a-fA-F]+)\s*\)\s*begin", code)
    if not excluded or int(excluded[1],16) != (1 << exponent_bits)-1:
        return rtl
    # Match the actual hidden-bit multiplication, including its unsigned
    # padding geometry. Metadata alone is not evidence about the operands.
    product = re.search(r'prod\s*=\s*\{\{' + str(p) + r"\{1'b0\}\},\s*1'b1,\s*"
                        r'(?P<frac>\w+|x\[\d+:0\])\}\s*\*\s*\{'
                        + str(fraction_bits+1) + r"'d0,\s*TWO_OVER_PI\}\s*;", code)
    if not product:
        return rtl
    fraction = re.escape(product['frac'])
    if product['frac'].startswith('x['):
        if product['frac'] != f'x[{fraction_bits-1}:0]':
            return rtl
    elif not re.search(r'wire\s*\[' + str(fraction_bits-1) + r':0\]\s*'
                       + fraction + r'\s*=\s*x(?:\[' + str(fraction_bits-1) + r':0\])?\s*;', code):
        return rtl
    if shift['exp'].startswith('x['):
        if shift['exp'] != f'x[{fraction_bits+exponent_bits-1}:{fraction_bits}]':
            return rtl
    elif not re.search(r'wire\s*\[' + str(exponent_bits-1) + r':0\]\s*'
                       + exp + r'\s*=\s*x\[' + str(fraction_bits+exponent_bits-1)
                       + ':' + str(fraction_bits) + r'\]\s*;', code):
        return rtl
    expression = (f'phase_nearest_integer = (prod + ({w+1}\'d1 << (shift_amt - 1))) >> shift_amt;\n'
                  '      quadrant = phase_nearest_integer;\n'
                  f'      phase_scaled_product = prod >> (shift_amt - {q});\n'
                  f'      fracq = phase_scaled_product - (phase_nearest_integer << {q});')
    result = rtl[:match.start()] + expression + rtl[match.end():]
    old = {'ipart', 'remainder', 'halfv', 'frac_wide', 'round_up'}
    # Do not remove a scratch identifier that is still consumed elsewhere.
    checking = re.sub(r'\breg\b[^;]*;', '', result)
    for name in old:
        checking = re.sub(r'\b' + name + r'\s*=\s*0\s*;', '', checking)
    if any(re.search(r'\b' + name + r'\b', checking) for name in old):
        return rtl
    # Only the quotient modulo 2**64 and the scaled product modulo 2**64
    # enter the residual; narrow those typed intermediates before subtraction.
    # The guard SUM remains w+1 bits by its sized unsigned half operand, and
    # the product remains w bits. This removes truly unobservable high-bit
    # arithmetic, rather than discarding product precision before rounding.
    result = result.replace(declaration[0], f'reg [{w-1}:0] prod;\n  reg [63:0] phase_nearest_integer, phase_scaled_product;', 1)
    for name in old:
        result = re.sub(r'\b' + name + r'\s*=\s*0\s*;', '', result)
    result = re.sub(r'\breg\s+round_up\s*;', '', result)
    result = re.sub(r'\breg\s+round_up\s*,', 'reg ', result)
    result = result.replace('prod = 0;', 'prod = 0; phase_nearest_integer = 0; phase_scaled_product = 0;', 1)
    # The full-width unsigned assignment context extends both multiplication
    # operands to w bits. Remove literal zero-padding without changing the
    # multiplier's result width; retain an explicit hidden-bit concatenation.
    padded_product = re.search(r'prod\s*=\s*\{\{' + str(p) + r"\{1'b0\}\},\s*1'b1,\s*"
                               + fraction + r'\}\s*\*\s*\{' + str(fraction_bits+1)
                               + r"'d0,\s*TWO_OVER_PI\}\s*;", result)
    if not padded_product:
        return rtl
    result = (result[:padded_product.start()] + "prod = {1'b1, " + product['frac']
              + '} * TWO_OVER_PI;' + result[padded_product.end():])
    return result


def compact_odd_saturation_guards(rtl: str, *, exponent_bits: int,
                                  fraction_bits: int) -> str:
    """Merge infinity into an existing magnitude saturation branch.

    NaN is magnitude > infinity. A finite monotone saturation threshold below
    infinity already covers infinity, so its duplicate signed constant branch
    is dead. DAZ, the identity region, and the entire finite kernel remain
    byte-for-byte unchanged. Unsupported guard structures fail closed.
    """
    if '`' in rtl or '/*' in rtl:
        return rtl
    n = exponent_bits + fraction_bits + 1
    if not 2 <= exponent_bits <= 10 or not 1 <= fraction_bits <= 30:
        return rtl
    # The typed comparison functions are required to have their established
    # exact integer meanings, rather than relying on function names.
    if not _comparison_contracts(rtl,('fp_eq','fp_ne','fp_le','fp_ge')):
        return rtl
    pattern = re.compile(
        r'if\s*\(fp_eq\((?P<exp>\w+),\s*' + str(exponent_bits) + r"'h(?P<maxexp>[0-9a-fA-F]+)\)\)\s*begin\s*"
        r'if\s*\(fp_ne\((?P<frac>\w+),\s*0\)\)\s*'
        r'y\s*=\s*(?P<nan>\d+\x27h[0-9a-fA-F]+)\s*;\s*else\s*'
        r'y\s*=\s*\{(?P<sign>\w+),\s*(?P<one>\d+\x27h[0-9a-fA-F]+)\}\s*;\s*'
        r'end\s*else\s*if\s*\(fp_eq\((?P=exp),\s*0\)\)\s*begin\s*'
        r'y\s*=\s*\{(?P=sign),\s*(?P<zero>\d+\x27d0)\}\s*;\s*end\s*'
        r'else\s*if\s*\(fp_le\((?P<mag>\w+),\s*(?P<small>\d+\x27h[0-9a-fA-F]+)\)\)\s*begin\s*'
        r'y\s*=\s*x\s*;\s*end\s*else\s*if\s*'
        r'\(fp_ge\((?P=mag),\s*(?P<sat>\d+\x27h[0-9a-fA-F]+)\)\)\s*begin\s*'
        r'y\s*=\s*\{(?P=sign),\s*(?P=one)\}\s*;\s*end\s*else\s*begin')
    matches = list(pattern.finditer(rtl))
    if len(matches) != 1:
        return rtl
    m = matches[0]
    infinity = ((1 << exponent_bits)-1) << fraction_bits
    small = int(m['small'].split("'h")[1], 16)
    sat = int(m['sat'].split("'h")[1], 16)
    if (int(m['maxexp'],16) != (1 << exponent_bits)-1
            or not (1 << fraction_bits) <= small < sat < infinity
            or int(m['one'].split("'h")[0]) != n-1
            or int(m['zero'].split("'d")[0]) != n-1):
        return rtl
    geometry = {'exp':(n-2,fraction_bits), 'frac':(fraction_bits-1,0),
                'mag':(n-2,0), 'sign':(n-1,n-1)}
    for name,(hi,lo) in geometry.items():
        signal = re.escape(m[name]); width = hi-lo+1
        select = str(hi) if hi == lo else str(hi)+':'+str(lo)
        vector = '' if width == 1 else r'\['+str(width-1)+r':0\]\s*'
        source = r'x\['+select+r'\]' if lo else r'x(?:\['+select+r'\])?'
        if not re.search(r'wire\s+' + vector + signal + r'\s*=\s*' + source + r'\s*;', rtl):
            return rtl
    replacement = (
        f"if (fp_ge({m['mag']}, {n-1}'d{infinity+1})) begin\n"
        f"      y = {m['nan']};\n"
        f"    end else if (fp_eq({m['exp']}, 0)) begin\n"
        f"      y = {{{m['sign']},{m['zero']}}};\n"
        f"    end else if (fp_le({m['mag']}, {m['small']})) begin\n"
        "      y = x;\n"
        f"    end else if (fp_ge({m['mag']}, {m['sat']})) begin\n"
        f"      y = {{{m['sign']},{m['one']}}};\n"
        "    end else begin")
    return rtl[:m.start()] + replacement + rtl[m.end():]


def compact_sigmoid_endpoint_guards(rtl: str, *, exponent_bits: int,
                                    fraction_bits: int) -> str:
    """Share the existing continuous endpoint regions with kernel isolation.

    For each sign the low interval joins DAZ into mag<=tiny; its high interval
    joins special values into mag>=sat. Special-value output priority remains
    unchanged. The interval bounds are taken from the existing guarded RTL,
    not inferred from benchmark addresses, and no new endpoint is introduced.
    """
    if '`' in rtl or '/*' in rtl or 'activation_tiny' in rtl:
        return rtl
    if not _comparison_contracts(rtl,('fp_eq','fp_ne','fp_le','fp_ge','fp_land')):
        return rtl
    n = 1 + exponent_bits + fraction_bits
    infinity = ((1 << exponent_bits)-1) << fraction_bits
    maxfinite = infinity-1
    pattern = re.compile(
        r'wire\s*\[' + str(n-1) + r':0\]\s*kernel_x\s*=\s*'
        r'\(\((?P<sign>\w+)\s*==\s*1\x27b0\s*&&\s*(?P<mag>\w+)\s*>=\s*'
        r'(?P<width>\d+)\x27h(?P<low>[0-9a-fA-F]+)\s*&&\s*(?P=mag)\s*<=\s*(?P=width)\x27h(?P<ptiny>[0-9a-fA-F]+)\)\s*\|\|\s*'
        r'\((?P=sign)\s*==\s*1\x27b0\s*&&\s*(?P=mag)\s*>=\s*(?P=width)\x27h(?P<psat>[0-9a-fA-F]+)\s*&&\s*(?P=mag)\s*<=\s*(?P=width)\x27h(?P<high>[0-9a-fA-F]+)\)\s*\|\|\s*'
        r'\((?P=sign)\s*==\s*1\x27b1\s*&&\s*(?P=mag)\s*>=\s*(?P=width)\x27h(?P=low)\s*&&\s*(?P=mag)\s*<=\s*(?P=width)\x27h(?P<ntiny>[0-9a-fA-F]+)\)\s*\|\|\s*'
        r'\((?P=sign)\s*==\s*1\x27b1\s*&&\s*(?P=mag)\s*>=\s*(?P=width)\x27h(?P<nsat>[0-9a-fA-F]+)\s*&&\s*(?P=mag)\s*<=\s*(?P=width)\x27h(?P=high)\)\s*\|\|\s*'
        r'\((?P<exp>\w+)\s*==\s*(?P<ewidth>\d+)\x27d0\)\s*\|\|\s*'
        r'\((?P=exp)\s*==\s*(?P=ewidth)\x27d(?P<special>\d+)\)\)\s*\?\s*'
        r'(?P<one>\d+\x27h[0-9a-fA-F]+)\s*:\s*x\s*;')
    matches = list(pattern.finditer(rtl))
    if len(matches) != 1:
        return rtl
    m = matches[0]
    values = {key:int(m[key],16) for key in ('low','high','ptiny','ntiny','psat','nsat')}
    if (int(m['width']) != n-1 or int(m['ewidth']) != exponent_bits
            or int(m['special']) != (1 << exponent_bits)-1
            or values['low'] != 1 << fraction_bits or values['high'] != maxfinite
            or not values['low'] <= values['ptiny'] < values['psat'] <= maxfinite
            or not values['low'] <= values['ntiny'] < values['nsat'] <= maxfinite):
        return rtl
    # Match the four corresponding output branches, so the same interval
    # predicate really controls both output selection and isolation.
    def condition(sign,low,high):
        return (r'fp_land\(fp_land\(fp_eq\(' + re.escape(m['sign']) + r",\s*1'b" + str(sign)
                + r'\),\s*fp_ge\(' + re.escape(m['mag']) + r",\s*" + m['width'] + r"'h" + low
                + r'\)\),\s*fp_le\(' + re.escape(m['mag']) + r",\s*" + m['width'] + r"'h" + high + r'\)\)')
    guards = re.compile(
        r'end\s+else\s+if\s*\(' + condition(0,m['low'],m['ptiny']) + r'\)\s*begin\s*'
        r'(?:\s*//[^\n]*\n)*\s*y\s*=\s*(?P<half>\d+\x27h[0-9a-fA-F]+)\s*;\s*'
        r'end\s+else\s+if\s*\(' + condition(0,m['psat'],m['high']) + r'\)\s*begin\s*'
        r'(?:\s*//[^\n]*\n)*\s*y\s*=\s*(?P<positive>\d+\x27h[0-9a-fA-F]+)\s*;\s*'
        r'end\s+else\s+if\s*\(' + condition(1,m['low'],m['ntiny']) + r'\)\s*begin\s*'
        r'(?:\s*//[^\n]*\n)*\s*y\s*=\s*(?P=half)\s*;\s*'
        r'end\s+else\s+if\s*\(' + condition(1,m['nsat'],m['high']) + r'\)\s*begin\s*'
        r'(?:\s*//[^\n]*\n)*\s*y\s*=\s*(?P<negative>\d+\x27h[0-9a-fA-F]+)\s*;\s*'
        r'end\s+else\s+if\s*\(fp_ne\((?P<localexp>\w+),\s*0\)\)\s*begin')
    endpoints = list(guards.finditer(rtl))
    if len(endpoints) != 1:
        return rtl
    g = endpoints[0]
    # Initial DAZ output must equal the small-region result, and infinity
    # saturation must select exactly the same signed endpoint constants.
    if not re.search(r'always\s*@\(\*\)\s*begin\s*y\s*=\s*' + re.escape(g['half']) + r'\s*;', rtl):
        return rtl
    saturation = re.compile(r'function\s*\['+str(n-1)+r':0\]\s*saturation\s*;\s*input\s+s\s*;\s*begin\s*'
                            r'if\s*\(s\)\s*saturation\s*=\s*'+re.escape(g['negative'])+r'\s*;\s*'
                            r'else\s*saturation\s*=\s*'+re.escape(g['positive'])+r'\s*;\s*end\s*endfunction')
    if not saturation.search(rtl) or g['positive'] != m['one']:
        return rtl
    # Unsigned primary field aliases are the only permitted guard operands.
    specs = ((m['mag'],n-2,0),(m['exp'],n-2,fraction_bits),(m['sign'],n-1,n-1))
    for signal,hi,lo in specs:
        vector = '' if hi == lo else r'\['+str(hi-lo)+r':0\]\s*'
        select = str(hi) if hi == lo else str(hi)+':'+str(lo)
        source = r'x\['+select+r'\]' if lo else r'x(?:\['+select+r'\])?'
        if not re.search(r'wire\s+'+vector+re.escape(signal)+r'\s*=\s*'+source+r'\s*;',rtl):
            return rtl
    if not re.search(r'\b'+re.escape(g['localexp'])+r'\s*=\s*'+re.escape(m['exp'])+r'\s*;',rtl):
        return rtl
    replacement = (
        'end else if (activation_tiny) begin\n'
        f"      y = {g['half']};\n"
        '    end else if (activation_saturated) begin\n'
        f"      y = {m['sign']} ? {g['negative']} : {g['positive']};\n"
        '    end else begin')
    result = rtl[:g.start()] + replacement + rtl[g.end():]
    m = pattern.search(result)
    replacement = (
        f"wire activation_tiny = {m['mag']} <= ({m['sign']} ? {m['width']}'h{m['ntiny']} : {m['width']}'h{m['ptiny']});\n"
        f"  wire activation_saturated = {m['mag']} >= ({m['sign']} ? {m['width']}'h{m['nsat']} : {m['width']}'h{m['psat']});\n"
        # Saturation starts below maxfinite, so it includes every special
        # magnitude. Tiny starts at zero, so it includes every DAZ magnitude.
        # Neither duplicate class test is needed for kernel isolation.
        f"  wire [{n-1}:0] kernel_x = (activation_tiny || activation_saturated) ? {m['one']} : x;")
    return result[:m.start()] + replacement + result[m.end():]


def linearize_normal_activation_pack(rtl: str, *, exponent_bits: int,
                                     fraction_bits: int,
                                     rounded_interval: tuple[int, int] | None = None) -> str:
    """Pack a normalized rounded significand by linear code arithmetic.

    For 2**F<=rounded<=2**(F+1), the hidden-bit contribution and the possible
    rounded carry are both expressed by (exponent+bias-1)*2**F+rounded.
    This preserves modulo exponent-field packing, including a carry at a
    binade boundary. The caller must establish the normalized-sig range, and
    complete-domain validation remains mandatory for the generated source.
    """
    if '`' in rtl or '/*' in rtl or not 2 <= exponent_bits <= 10 or not 1 <= fraction_bits <= 30:
        return rtl
    # An explicit mathematical range contract is required; a syntactically
    # similar arbitrary packing expression is insufficient evidence.
    if rounded_interval != (1 << fraction_bits,1 << (fraction_bits+1)):
        return rtl
    if not _typed_helper(rtl,'fp_add',result_bits=64,expressions=('a+b','semantic_add65(a,b)')):
        return rtl
    if re.search(r'fp_add\s*=\s*semantic_add65\(a,\s*b\)',rtl):
        if not _typed_helper(rtl,'semantic_add65',input_bits=65,result_bits=65,expressions=('a+b',)):
            return rtl
    bias = (1 << (exponent_bits-1))-1
    pattern = re.compile(
        r'out_exp\s*=\s*fp_add\(fp_add\(bin_exp,\s*' + str(bias) + r'\),\s*rounded\[' + str(fraction_bits+1) + r'\]\)\s*;\s*'
        r'y\[' + str(exponent_bits+fraction_bits-1) + ':' + str(fraction_bits) + r'\]\s*=\s*out_exp\[' + str(exponent_bits-1) + r':0\]\s*;\s*'
        r'y\[' + str(fraction_bits-1) + r':0\]\s*=\s*rounded\[' + str(fraction_bits-1) + r':0\]\s*;')
    matches = list(pattern.finditer(rtl))
    if len(matches) != 1:
        return rtl
    # Require the full-width signed accumulator used by the original pack.
    if not re.search(r'reg\s+signed\s*\[63:0\]\s*[^;]*\bout_exp\b[^;]*;',rtl):
        return rtl
    match = matches[0]
    replacement = (f'out_exp = fp_add((fp_add(bin_exp, {bias-1}) * {1<<fraction_bits}), rounded);\n'
                   f'        y[{exponent_bits+fraction_bits-1}:0] = out_exp;')
    return rtl[:match.start()] + replacement + rtl[match.end():]


def share_periodic_word_addition(rtl: str) -> str:
    """Reuse a proven modular 64-bit adder for phase/control subtraction.

    Shift controls remain explicitly signed-32 integer temporaries; only their
    small, nonnegative mathematical values are produced by the word adder.
    Residual subtraction is modulo 2**64, exactly matching the established
    typed-64 reduction. No multiplication, polynomial or rounding is changed.
    """
    if ('`' in rtl or '/*' in rtl or 'phase_half_shift' in rtl
            or not _typed_helper(rtl,'fp_add',result_bits=64,expressions=('a+b','semantic_add65(a,b)'))):
        return rtl
    if re.search(r'fp_add\s*=\s*semantic_add65\(a,\s*b\)',rtl):
        if not _typed_helper(rtl,'semantic_add65',input_bits=65,result_bits=65,expressions=('a+b',)):
            return rtl
    pattern = re.compile(
        r'shift_amt\s*=\s*(?P<bias>\d+)\s*-\s*(?P<exp>\w+)\s*;\s*'
        r'phase_nearest_integer\s*=\s*\(prod\s*\+\s*\((?P<w>\d+)\x27d1\s*<<\s*\(shift_amt\s*-\s*1\)\)\)\s*>>\s*shift_amt\s*;\s*'
        r'quadrant\s*=\s*phase_nearest_integer\s*;\s*'
        r'phase_scaled_product\s*=\s*prod\s*>>\s*\(shift_amt\s*-\s*(?P<q>\d+)\)\s*;\s*'
        r'fracq\s*=\s*phase_scaled_product\s*-\s*\(phase_nearest_integer\s*<<\s*(?P=q)\)\s*;')
    matches = list(pattern.finditer(rtl))
    if len(matches) != 1 or not re.search(r'reg\s*\[63:0\]\s*phase_nearest_integer,\s*phase_scaled_product\s*;',rtl):
        return rtl
    m=matches[0]
    exp = re.search(r'wire\s*\[(\d+):0\]\s*'+re.escape(m['exp'])+r'\s*=\s*x\[\d+:\d+\]\s*;',rtl)
    if not exp or not (2 <= int(exp[1])+1 <= 10):
        return rtl
    bias=int(m['bias']);q=int(m['q'])
    if not (q < bias < (1<<30) and bias-((1<<(int(exp[1])+1))-1)>=q):
        return rtl
    replacement=(f"shift_amt = fp_add({bias}, (-{m['exp']}));\n"
                 "      phase_half_shift = fp_add(shift_amt, (-1));\n"
                 f"      phase_fraction_shift = fp_add(shift_amt, (-{q}));\n"
                 f"      phase_nearest_integer = (prod + ({m['w']}'d1 << phase_half_shift)) >> shift_amt;\n"
                 "      quadrant = phase_nearest_integer;\n"
                 "      phase_scaled_product = prod >> phase_fraction_shift;\n"
                 f"      fracq = fp_add(phase_scaled_product, (-(phase_nearest_integer << {q})));")
    result=rtl[:m.start()]+replacement+rtl[m.end():]
    declaration=re.search(r'integer\s+shift_amt\s*;',result)
    if not declaration:return rtl
    result=result[:declaration.start()]+'integer shift_amt, phase_half_shift, phase_fraction_shift;'+result[declaration.end():]
    return result.replace('shift_amt = 0;','shift_amt = 0; phase_half_shift = 0; phase_fraction_shift = 0;',1)


def compact_periodic_output_controls(rtl: str) -> str:
    """Share quadrant, sign, absolute-value and zero-result word selection.

    Both sine/cosine polynomial bodies and all intermediate truncations stay
    intact. Zero normalization has only defined arithmetic; its packed value
    is suppressed at the output, retaining the input's zero sign. Unsupported
    source shapes or arithmetic helper contracts are returned unchanged.
    """
    if ('`' in rtl or '/*' in rtl or 'periodic_select64' in rtl
            or not _comparison_contracts(rtl,('fp_eq',))):
        return rtl
    if not _typed_helper(rtl,'fp_add',result_bits=64,expressions=('a+b','semantic_add65(a,b)')):
        return rtl
    if re.search(r'fp_add\s*=\s*semantic_add65\(a,\s*b\)',rtl):
        if not _typed_helper(rtl,'semantic_add65',input_bits=65,result_bits=65,expressions=('a+b',)):
            return rtl
    if not _typed_helper(rtl,'fp_mul',result_bits=64,expressions=('a*b','semantic_multiply128(a,b)')):
        return rtl
    if re.search(r'fp_mul\s*=\s*semantic_multiply128\(a,\s*b\)',rtl):
        if not _typed_helper(rtl,'semantic_multiply128',result_bits=128,expressions=('a*b',)):
            return rtl
    rounding=re.search(r'\bfunction\s+signed\s*\[63:0\]\s+semantic_rne64\s*;.*?\bendfunction\b',rtl,re.S)
    if not rounding:return rtl
    rounding_contract=re.compile(
        r'function\s+signed\s*\[63:0\]\s+semantic_rne64\s*;\s*'
        r'input\s+signed\s*\[63:0\]\s+value\s*;\s*input\s*\[5:0\]\s+shift\s*;\s*'
        r'input\s+signed\s*\[64:0\]\s+bias\s*;\s*reg\s+signed\s*\[64:0\]\s+extended\s*;\s*'
        r'begin\s*extended\s*=\s*value\s*;\s*'
        r'extended\s*=\s*semantic_add65\(extended,\s*bias\)\s*;\s*'
        r'extended\s*=\s*semantic_add65\(extended,\s*value\[shift\]\)\s*;\s*'
        r'semantic_rne64\s*=\s*extended\s*>>>\s*shift\s*;\s*end\s*endfunction')
    if not rounding_contract.fullmatch(rounding[0]):return rtl
    pattern = re.compile(
        r'if\s*\(fp_eq\(quadrant,\s*0\)\)\s*valueq\s*=\s*sinv\s*;\s*'
        r'else\s*if\s*\(fp_eq\(quadrant,\s*1\)\)\s*valueq\s*=\s*cosv\s*;\s*'
        r'else\s*if\s*\(fp_eq\(quadrant,\s*2\)\)\s*valueq\s*=\s*\(-sinv\)\s*;\s*'
        r'else\s*valueq\s*=\s*\(-cosv\)\s*;\s*'
        r'if\s*\((?P<sign>\w+)\)\s*valueq\s*=\s*\(-valueq\)\s*;')
    matches=list(pattern.finditer(rtl))
    if len(matches)!=1:return rtl
    m=matches[0];sign=m['sign']
    sign_decl=re.search(r'wire\s+'+re.escape(sign)+r'\s*=\s*x\[15\]\s*;',rtl)
    if not sign_decl:return rtl
    # This source family has a pure bounded normalization/RNE block. In
    # particular it contains no reciprocal or division by a value-dependent
    # denominator when normalization is evaluated at zero.
    zero=re.search(r'if\s*\(fp_eq\(valueq,\s*0\)\)\s*begin\s*'
                   r'y\s*=\s*\{'+re.escape(sign)+r",\s*15'd0\}\s*;\s*end\s*else\s*begin",rtl[m.end():])
    if not zero:return rtl
    start=m.end()+zero.start();body_start=m.end()+zero.end()
    depth=1;body_end=None
    for token in re.finditer(r'\bbegin\b|\bend\b',rtl[body_start:]):
        depth += 1 if token[0]=='begin' else -1
        if depth==0:body_end=body_start+token.start();closing_end=body_start+token.end();break
    if body_end is None:return rtl
    body=rtl[body_start:body_end]
    allowed=re.compile(
        r'\s*absq\s*=\s*\(valueq\[63\]\s*\?\s*\(-valueq\)\s*:\s*valueq\)\s*;\s*'
        r'normq\s*=\s*absq\s*;\s*bin_exp\s*=\s*0\s*;\s*'
        r'for\s*\(i\s*=\s*0;\s*i\s*<\s*60;\s*i\s*=\s*i\s*\+\s*1\)\s*'
        r'if\s*\(normq\s*<\s*ONE\)\s*begin\s*normq\s*=\s*normq\s*<<<\s*1\s*;\s*'
        r'bin_exp\s*=\s*bin_exp\s*-\s*1\s*;\s*end\s*'
        r'rounded32\s*=\s*semantic_rne64\(normq,\s*6\x27d33,\s*65\x27sd4294967295\)\s*;\s*'
        r'rounded\s*=\s*semantic_rne64\(rounded32,\s*6\x27d16,\s*65\x27sd32767\)\s*;\s*'
        r'out_exp\s*=\s*fp_add\(fp_mul\(\(fp_add\(bin_exp,\s*126\)\),\s*128\),\s*rounded\)\s*;\s*'
        r'begin\s*semantic_packed_magnitude\s*=\s*out_exp\s*;\s*'
        r'y\s*=\s*fp_add\(fp_mul\(valueq\[63\],\s*16\x27d32768\),\s*semantic_packed_magnitude\)\s*;\s*end\s*')
    if not allowed.fullmatch(body):return rtl
    replacement=('valueq = periodic_select64(quadrant[0], cosv, sinv);\n'
                 '      valueq = periodic_select64(quadrant[1], (-valueq), valueq);\n'
                 f'      valueq = periodic_select64({sign}, (-valueq), valueq);')
    body=body.replace('(valueq[63] ? (-valueq) : valueq)','periodic_select64(valueq[63], (-valueq), valueq)')
    body=re.sub(r'semantic_packed_magnitude\s*=\s*out_exp\s*;',
                'semantic_packed_magnitude = periodic_select64(fp_eq(valueq, 0), 0, out_exp);',body)
    body=body.replace("fp_mul(valueq[63], 16'd32768)",
                      f"fp_mul(periodic_select64(fp_eq(valueq, 0), {sign}, valueq[63]), 16'd32768)")
    result=rtl[:start]+body+rtl[closing_end:]
    result=result[:m.start()]+replacement+result[m.end():]
    helper=('  function signed [63:0] periodic_select64;\n'
            '    input signed [63:0] condition;\n'
            '    input signed [63:0] a, b;\n'
            '    begin periodic_select64 = condition ? a : b; end\n'
            '  endfunction\n\n')
    return result.replace('  always @(*) begin',helper+'  always @(*) begin',1)

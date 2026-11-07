"""Conservative structural compaction for generated semantic RTL.

The transformations never inspect filenames or truth-table contents. They
share static input fields and a complete fixed-width ties-to-even operation;
generated candidates still require complete-domain frontend verification.
"""
from __future__ import annotations

from collections import Counter
import re
from truth.protect_word_loops import compact_outside_word_loops
from truth.dynamic_round_compact_v8 import share_dynamic_round_to_even
from truth.rtl_cost_selection import lowest_cost_source
from truth.transcendental_compact_v9 import compact_transcendental_word_semantics
from truth.periodic_activation_compact_v9 import (
    compact_periodic_phase, share_periodic_word_addition,
    compact_periodic_output_controls, compact_odd_saturation_guards,
    compact_sigmoid_endpoint_guards, linearize_normal_activation_pack,
)


def share_input_fields(rtl: str) -> str:
    """Name repeated unsigned slices of the sole primary input, x.

    Touch only numeric selects, never dynamic indexing, assignment targets,
    signed ports, macros, or helper scopes. A fresh net has the same unsigned
    width as the original Verilog select.
    """
    port = re.search(r'module\s+top\s*\(input\s*\[(\d+):0\]\s*x\b[^;]*;', rtl)
    scope_texts = [match[0] for match in re.finditer(
        r'\b(?:function|task)\b.*?\bend(?:function|task)\b', rtl, flags=re.S)]
    if not port or any(re.search(r'\bx\b', scope) for scope in scope_texts):
        return rtl
    # Comments must not influence the choice or be rewritten as circuit code.
    if '/*' in rtl or '`' in rtl:
        return rtl
    lines = rtl.splitlines(keepends=True)
    pattern = re.compile(r'\bx\[(\d+)(?::(\d+))?\]')
    counts: Counter[tuple[int, int]] = Counter()
    for line in lines:
        code = line.split('//', 1)[0]
        for match in pattern.finditer(code):
            hi, lo = int(match[1]), int(match[2] or match[1])
            if 0 <= lo <= hi <= int(port[1]):
                counts[(hi, lo)] += 1
    fields = [field for field, count in sorted(counts.items()) if count >= 2]
    if not fields:
        return rtl
    names = {field: f'input_field_{field[0]}_{field[1]}' for field in fields}
    if any(re.search(r'\b' + name + r'\b', rtl) for name in names.values()):
        return rtl
    def replace(match: re.Match[str]) -> str:
        field = int(match[1]), int(match[2] or match[1])
        return names.get(field, match[0])
    changed = []
    for line in lines:
        code, separator, comment = line.partition('//')
        changed.append(pattern.sub(replace, code) + separator + comment)
    result = ''.join(changed)
    declarations = []
    for (hi, lo), name in names.items():
        width = hi - lo + 1
        geometry = '' if width == 1 else f'[{width - 1}:0] '
        select = str(hi) if hi == lo else f'{hi}:{lo}'
        expression = 'x' if lo == 0 else f'x[{select}]'
        declarations.append(f'\n  wire {geometry}{name} = {expression};')
    # The module header cannot contain an input select, so its offset is stable.
    return result[:port.end()] + ''.join(declarations) + result[port.end():]


_ROUND = re.compile(
    r'(?P<indent>^[ \t]*)(?P<dst>\w+)\s*=\s*(?P<src>\w+)\s*>>>\s*(?P<shift>\d+)\s*;\s*'
    r'(?P<rem>\w+)\s*=\s*(?P=src)\s*-\s*\((?P=dst)\s*<<<\s*(?P=shift)\)\s*;\s*'
    r'if\s*\(\s*\((?P=rem)\s*>\s*64\x27sd(?P<half>\d+)\)\s*\|\|\s*'
    r'\(\((?P=rem)\s*==\s*64\x27sd(?P=half)\)\s*&&\s*(?P=dst)\[0\]\)\s*\)\s*'
    r'(?P=dst)\s*=\s*(?P=dst)\s*\+\s*1\s*;', re.M)


def share_round_to_even(rtl: str) -> str:
    """Share repeated exact signed-64 right-shift round-to-nearest-even.

    A 65-bit sum prevents intermediate overflow for every signed-64 input,
    including negative values. The original floor quotient/remainder test is
    exactly (value + 2**(shift-1)-1 + quotient_lsb) >> shift. The destination
    still truncates to 64 bits, matching overflow in the original increment.
    Scratch remainder assignments are removed only when their next use is a
    definite overwrite; functions and unsupported scopes fail closed.
    """
    marker = '  always @(*) begin'
    if marker not in rtl or '\x60' in rtl or 'semantic_rne64' in rtl:
        return rtl
    header, body = rtl.split(marker, 1)
    declaration_scope = re.sub(r'\b(function|task)\b.*?\bend(?:function|task)\b', '', header, flags=re.S)
    signed64 = set()
    for declaration in re.finditer(r'\breg\s+signed\s*\[63:0\]\s*([^;]+);', declaration_scope):
        for name in declaration[1].split(','):
            if re.fullmatch(r'\s*\w+\s*', name):
                signed64.add(name.strip())
    matches = []
    for match in _ROUND.finditer(body):
        shift = int(match['shift'])
        if not (1 <= shift <= 63) or int(match['half']) != 1 << (shift - 1):
            continue
        if not {match['dst'], match['src'], match['rem']} <= signed64:
            continue
        if len({match['dst'], match['src'], match['rem']}) != 3:
            continue
        matches.append(match)
    # A scratch value is dead only if every later read belongs to another
    # recognized rounding block, which computes its own remainder first.
    # Merely seeing a conditional assignment is not a definite overwrite.
    safe_remainders = set()
    for remainder in {match['rem'] for match in matches}:
        grouped = [match for match in matches if match['rem'] == remainder]
        checking = body[grouped[0].start():]
        base = grouped[0].start()
        for match in reversed(grouped):
            checking = checking[:match.start()-base] + checking[match.end()-base:]
        checking = re.sub(r'//[^\n]*|/\*.*?\*/', '', checking, flags=re.S)
        if all(re.match(r'\s*=(?!=)', checking[use.end():])
               for use in re.finditer(r'\b' + re.escape(remainder) + r'\b', checking)):
            safe_remainders.add(remainder)
    matches = [match for match in matches if match['rem'] in safe_remainders]
    if len(matches) < 2:
        return rtl
    for match in reversed(matches):
        body = body[:match.start()] + (
            f"{match['indent']}{match['dst']} = semantic_rne64({match['src']}, 6'd{match['shift']}, 65'sd{int(match['half'])-1});") + body[match.end():]
    helper = '''  // Exact signed round-to-nearest-even; shift is between 1 and 63.
  function signed [63:0] semantic_rne64;
    input signed [63:0] value;
    input [5:0] shift;
    input signed [64:0] bias;
    reg signed [64:0] extended;
    begin
      extended = value;
      extended = extended + bias;
      extended = extended + value[shift];
      semantic_rne64 = extended >>> shift;
    end
  endfunction

'''
    return header + helper + marker + body


def linearize_float_pack(rtl: str) -> str:
    """Fold significand carry into packed binary-format addition.

    Exact intermediate and final RNE stages remain in order. A rounded
    significand of 2**(f+1) is naturally the next exponent in the linear
    encoding (exponent-1)*2**f+significand. Specialized exponent-zero
    subnormal rounding branches remain intact, including FTZ promotion.
    """
    if '  always @(*) begin' not in rtl:
        return rtl
    if re.search(r'\bsemantic_packed_magnitude\b', rtl):
        return rtl
    assignments = list(re.finditer(r'\bout_exp\s*=\s*bin_exp\s*\+\s*(127|15)\s*;', rtl))
    if len(assignments) != 1:
        return rtl
    bias = int(assignments[0][1])
    f, e = (7, 8) if bias == 127 else (10, 5)
    scale, maximum = 1 << f, (1 << e)-1
    final_carry = re.compile(
        rf'if\s*\(rounded\s*>=\s*{2*scale}\)\s*begin\s*'
        rf'rounded\s*=\s*{scale}\s*;\s*(bin_exp|out_exp)\s*=\s*\1\s*\+\s*1\s*;\s*end')
    carries = list(final_carry.finditer(rtl))
    if len(carries) != 1:
        return rtl
    carry_target = carries[0][1]
    pack = re.compile(rf'\by\s*=\s*\{{\s*(?:(?P<sign>[^,{{}}]+),\s*)?out_exp\[{e-1}:0\]\s*,\s*(rounded|sig)\[{f-1}:0\]\s*\}}\s*;')
    packs = list(pack.finditer(rtl))
    if len(packs) != 1:
        return rtl
    if not re.search(r'\breg\s+signed\s*\[63:0\]\s*[^;]*\bout_exp\b', rtl):
        return rtl
    intermediate = re.compile(r'if\s*\(rounded32\s*>=\s*16777216\)\s*begin\s*'
                              r'rounded32\s*=\s*8388608\s*;\s*bin_exp\s*=\s*bin_exp\s*\+\s*1\s*;\s*end')
    if len(list(intermediate.finditer(rtl))) > 1:
        return rtl
    result = intermediate.sub('', rtl)
    if carry_target == 'bin_exp':
        result = final_carry.sub('', result)
        result = re.sub(r'\bout_exp\s*=\s*bin_exp\s*\+\s*(127|15)\s*;',
                        f'out_exp = (bin_exp + {bias-1}) * {scale} + rounded;', result)
        boundary = result.index(f'out_exp = (bin_exp + {bias-1})')
    else:
        replacement = f'out_exp = (out_exp - 1) * {scale} + rounded;'
        result = final_carry.sub(replacement, result)
        boundary = result.index(replacement)
    # Only conditions after packing change units. Earlier exponent-zero
    # branches still operate on the original exponent and retain their shift.
    prefix, tail = result[:boundary], result[boundary:]
    tail = re.sub(r'\bout_exp\s*<=\s*0\b', f'out_exp < {scale}', tail)
    tail = re.sub(rf'\bout_exp\s*>=\s*{maximum}\b', f'out_exp >= {maximum*scale}', tail)
    sign_scope = re.sub(r'\b(function|task)\b.*?\bend(?:function|task)\b', '',
                        rtl.split('  always @(*) begin', 1)[0], flags=re.S)
    sign_bits = set(re.findall(r'\b(?:wire|reg)\s+(\w+)\s*(?:[=;])', sign_scope))
    replacement_outputs = []
    def packed_output(match):
        sign = match['sign']
        if sign is None or sign.strip() in ("1'b0", "1'd0"):
            return 'y = out_exp;'
        sign = sign.strip()
        # Assignment to a width-limited magnitude preserves truncation before
        # arithmetic sign insertion. Existing word helpers can
        # share these add/multiply operations with the rest of the datapath.
        if sign in sign_bits or re.fullmatch(r'\w+\[\d+\]', sign):
            output = ("begin\n        semantic_packed_magnitude = out_exp;\n        "
                      f"y = {sign} * {e+f+1}'d{1 << (e+f)} + semantic_packed_magnitude;\n      end")
            replacement_outputs.append(output)
            return output
        return f'y = {{{sign}, out_exp[{e+f-1}:0]}};'
    tail = pack.sub(packed_output, tail)
    # All uses after the unit conversion must be explicitly accounted for.
    # Unknown exponent guards or further arithmetic retain the original RTL.
    checking = re.sub(r'//[^\n]*|/\*.*?\*/', '', tail, flags=re.S)
    checking = re.sub(r'^out_exp\s*=[^;]*;', '', checking, count=1)
    checking = re.sub(rf'\bout_exp\s*(?:<\s*{scale}|>=\s*{maximum*scale})\b', '', checking)
    checking = re.sub(r'\by\s*=\s*out_exp\s*;', '', checking)
    for output in replacement_outputs:
        checking = checking.replace(output, '')
    checking = re.sub(rf'\by\s*=\s*\{{[^,{{}}]+,\s*out_exp\[{e+f-1}:0\]\s*\}}\s*;', '', checking)
    if re.search(r'\bout_exp\b', checking):
        return rtl
    result = prefix + tail
    if replacement_outputs:
        result = result.replace('  always @(*) begin',
            f'  reg [{e+f-1}:0] semantic_packed_magnitude;\n'
            '  always @(*) begin\n    semantic_packed_magnitude = 0;', 1)
    if packs[0][2] == 'sig':
        result = re.sub(rf'\bsig\s*=\s*rounded\[{f}:0\]\s*;', '', result)
    return result


def reduce_positive_padding(rtl: str) -> str:
    """Use arithmetic context widths for positive unsigned field decoding.

    A sized 64-bit constant already extends an unsigned fraction before
    addition. Cast the full positive sum, preserving signed shift semantics,
    instead of separately concatenating a redundant zero before the field.
    """
    marker = '  always @(*) begin'
    if marker not in rtl:
        return rtl
    header, body = rtl.split(marker, 1)
    widths = {}
    for match in re.finditer(r'\bwire\s*\[(\d+):0\]\s*(\w+)\s*=', header):
        widths[match[2]] = int(match[1])+1
    atom = r'(?:x\[\d+(?::\d+)?\]|[A-Za-z_]\w*)'
    def width_of(text):
        select = re.fullmatch(r'x\[(\d+)(?::(\d+))?\]', text)
        if select:
            return int(select[1])-int(select[2] or select[1])+1
        return widths.get(text)
    pattern = re.compile(rf"64'sd(\d+)\s*\+\s*\$signed\(\{{\s*1'b0\s*,\s*({atom})\s*\}}\)")
    def replace(match):
        width = width_of(match[2])
        if width is None or width < 1 or int(match[1]) + (1 << width)-1 >= 1 << 63:
            return match[0]
        return f"$signed(64'd{match[1]} + {match[2]})"
    body = pattern.sub(replace, body)
    padding = re.compile(rf"\{{\s*1'b0\s*,\s*({atom})\s*\}}(\s*[+-]\s*)(\d+)'([dDhH])([0-9a-fA-F]+)")
    def replace_small(match):
        width = width_of(match[1])
        return (match[1] + match[2] + match[3] + "'" + match[4] + match[5]
                if width is not None and int(match[3]) >= width+1 else match[0])
    body = padding.sub(replace_small, body)
    return header + marker + body


def compact_semantic_rtl(rtl: str, *,
                         normalized_activation_format: tuple[int, int] | None = None) -> str:
    candidates = []
    for phase in dict.fromkeys([rtl, compact_periodic_phase(rtl)]):
        prepared = share_round_to_even(linearize_float_pack(reduce_positive_padding(phase)))
        rounded = share_dynamic_round_to_even(prepared)
        candidates.extend(_finish_semantic_compaction(source, minimum,
                          normalized_activation_format=normalized_activation_format)
                          for source in dict.fromkeys([prepared, rounded])
                          for minimum in (1, 2))
    return lowest_cost_source(candidates)


def _finish_semantic_compaction(rtl: str, min_word_operator_uses: int = 1, *,
                         normalized_activation_format: tuple[int, int] | None = None) -> str:
    # Match the established signed fixed-point emitter contract. Unsigned
    # 64-bit integer quotients/roots and previously compacted helpers stay
    # unchanged; signedness and truncation are part of the representation.
    declaration_scope = re.sub(r'\b(function|task)\b.*?\bend(?:function|task)\b', '',
                              rtl.split('  always @(*) begin', 1)[0], flags=re.S)
    incompatible_width = any(int(match[2]) > 63 or (not match[1] and int(match[2]) == 63)
        for match in re.finditer(r'\b(?:reg|wire)\s*(signed\s+)?\[(\d+):0\]', declaration_scope))
    if (re.search(r'\breg\s+signed\s*\[63:0\]', declaration_scope)
            and not incompatible_width
            and not re.search(r'\bfunction\b[^;]*\bfp_\w+', rtl)):
        rtl = compact_outside_word_loops(rtl,
                         min_word_operator_uses=min_word_operator_uses)
    rtl = share_input_fields(share_signed_operators(rtl))
    periodic = share_periodic_word_addition(rtl)
    variants = list(dict.fromkeys([rtl, periodic, compact_periodic_output_controls(periodic)]))
    for source in tuple(variants):
        for e, f in ((8, 7), (5, 10)):
            variants.append(compact_odd_saturation_guards(source,
                            exponent_bits=e, fraction_bits=f))
            variants.append(compact_sigmoid_endpoint_guards(source,
                            exponent_bits=e, fraction_bits=f))
    if normalized_activation_format is not None:
        # Only an emitter with a proved positive normalized-significand
        # contract may request this packing alternative. Ordinary semantic
        # compaction does not assert an interval for arbitrary source RTL.
        e, f = normalized_activation_format
        variants.extend(linearize_normal_activation_pack(source,
                        exponent_bits=e, fraction_bits=f,
                        rounded_interval=(1 << f, 1 << (f+1)))
                        for source in tuple(dict.fromkeys(variants)))
    candidates = []
    for source in dict.fromkeys(variants):
        candidates.extend([source, compact_transcendental_word_semantics(source)])
    return lowest_cost_source(candidates)


def share_signed_operators(rtl: str) -> str:
    """Share exact modulo-64 add/subtract and reflected comparisons.

    Apply only to the known signed-64 helper definitions. In particular,
    negating INT64_MIN remains INT64_MIN under the same 64-bit wrap semantics.
    """
    def definition(name, operator, scalar=False):
        result = '' if scalar else r'signed\s*\[63:0\]\s*'
        return re.compile(rf'function\s+{result}{name}\s*;\s*'
            rf'input\s+signed\s*\[63:0\]\s*a\s*,\s*b\s*;\s*'
            rf'begin\s*{name}\s*=\s*a\s*{re.escape(operator)}\s*b\s*;\s*end\s*endfunction')
    if definition('fp_add', '+').search(rtl):
        pattern = definition('fp_sub', '-')
        rtl = pattern.sub(lambda m: re.sub(r'fp_sub\s*=\s*a\s*-\s*b', 'fp_sub = fp_add(a, -b)', m[0]), rtl)
    for direct, reflected, operator, opposite in [('fp_gt','fp_lt','>','<'),('fp_ge','fp_le','>=','<=')]:
        if definition(reflected, opposite, scalar=True).search(rtl):
            pattern = definition(direct, operator, scalar=True)
            rtl = pattern.sub(lambda m: re.sub(rf'{direct}\s*=\s*a\s*{re.escape(operator)}\s*b',
                f'{direct} = {reflected}(b, a)', m[0]), rtl)
    # Widened arithmetic helpers preserve the context width at every caller.
    # In particular, the signed-64 wrapper truncates only at its return, while
    # rounding retains the original 65-bit intermediate after each addition.
    if ('semantic_add65' not in rtl and definition('fp_add', '+').search(rtl)
            and re.search(r'function signed \[63:0\] semantic_rne64;', rtl)
            and 'extended = extended + bias;' in rtl
            and 'extended = extended + value[shift];' in rtl):
        rtl = rtl.replace('fp_add = a + b;', 'fp_add = semantic_add65(a, b);')
        rtl = rtl.replace('extended = extended + bias;', 'extended = semantic_add65(extended, bias);')
        rtl = rtl.replace('extended = extended + value[shift];', 'extended = semantic_add65(extended, value[shift]);')
        helper = '''  function signed [64:0] semantic_add65;
    input signed [64:0] a, b;
    begin semantic_add65 = a + b; end
  endfunction

'''
        rtl = rtl.replace('  always @(*) begin', helper+'  always @(*) begin', 1)
    if 'semantic_multiply128' not in rtl and definition('fp_mul', '*').search(rtl):
        product = re.compile(r'(function signed \[63:0\] \w+;\s*'
            r'input signed \[63:0\] a;\s*input signed \[63:0\] b;\s*'
            r'reg signed \[127:0\] (?P<product>\w+);\s*begin\s*)'
            r'(?P=product)\s*=\s*a\s*\*\s*b\s*;')
        if product.search(rtl):
            rtl = product.sub(lambda m:m[1]+f"{m['product']} = semantic_multiply128(a, b);",rtl)
            rtl = rtl.replace('fp_mul = a * b;', 'fp_mul = semantic_multiply128(a, b);')
            helper='''  function signed [127:0] semantic_multiply128;
    input signed [63:0] a, b;
    begin semantic_multiply128 = a * b; end
  endfunction

'''
            rtl = rtl.replace('  always @(*) begin',helper+'  always @(*) begin',1)
    return rtl


def emit_binary_square(exponent_width: int, fraction_width: int, detail: str) -> str:
    """Normalized binary square with fused RNE bias and DAZ/FTZ guards.

    The leading-bit normalization has only two shifts. Adding half-minus-one
    implements ties-to-even before either shift because square halfway cases
    always have an even retained quotient.
    The widened exponent includes both normalization and rounding carries.
    An exponent-zero input necessarily underflows for the supported biases,
    so no extra input-subnormal mux is required.
    """
    if exponent_width < 3 or fraction_width < 1:
        raise ValueError('binary square needs exponent width >= 3 and a fraction')
    e, f = exponent_width, fraction_width
    width, bias = 1 + e + f, (1 << (e - 1)) - 1
    max_exponent = (1 << e) - 1
    quiet_nan = (max_exponent << f) | (1 << (f - 1))
    infinity = max_exponent << f
    # One extra bit keeps the bias addition exact even at the largest product.
    product_width, exponent_calc_width = 2 * (f + 1), e + 2
    return f'''// {detail}
// Binary square: normalized significand multiplication and fused exact RNE.
module top(input [{width-1}:0] x, output [{width-1}:0] y);
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{f-1}:0] fraction = x;
  wire [{f}:0] significand = {f+1}'d{1 << f} + fraction;
  wire [{product_width-1}:0] product = significand * significand;
  wire normalize = product[{product_width-1}];
  wire [7:0] rounding_shift = {f} + normalize;
  // Every exact halfway square has an even retained quotient. Half-minus-one
  // therefore implements ties-to-even without a separate retained-LSB term.
  wire [{f+1}:0] rounded = (product +
      (normalize ? {product_width+1}'d{(1 << f)-1} : {product_width+1}'d{(1 << (f-1))-1})) >> rounding_shift;
  wire signed [{width+1}:0] packed_result = (exponent - {width+2}'d{(bias+1)//2}) *
      {width+2}'d{1 << (f+1)} + normalize * {width+2}'d{1 << f} + rounded;
  assign y = exponent == {e}'d{max_exponent} ?
      (fraction ? {width}'h{quiet_nan:x} : {width}'h{infinity:x}) :
      packed_result < {width+2}'sd{1 << f} ? {width}'d0 :
      packed_result >= {width+2}'sd{infinity} ? {width}'h{infinity:x} :
      packed_result;
endmodule
'''


def emit_binary_reciprocal(exponent_width: int, fraction_width: int, detail: str) -> str:
    """Exact reciprocal of a normalized binary significand, with DAZ/FTZ.

    Rounding 2**(2*f+1)/denominator cannot encounter a halfway fraction:
    a tie would require denominator/2 to divide a power of two, and the only
    power-of-two denominator in [2**f,2**(f+1)) is its exact lower endpoint.
    Thus adding floor(denominator/2) before division gives exact RNE. This
    single quotient covers the unit-significand endpoint as a rounding carry.
    Normal inputs cannot overflow; DAZ zero has its explicit infinity result.
    """
    if exponent_width < 3 or fraction_width < 1:
        raise ValueError('binary reciprocal needs exponent width >= 3 and a fraction')
    e, f = exponent_width, fraction_width
    width, bias = 1 + e + f, (1 << (e-1))-1
    maximum = (1 << e)-1
    numerator = 1 << (2*f+1)
    infinity = maximum << f
    quiet_nan = infinity | (1 << (f-1))
    return f'''// {detail}
// Binary reciprocal: one rounded significand quotient, DAZ input, FTZ output.
module top(input [{width-1}:0] x, output [{width-1}:0] y);
  wire sign_in = x[{width-1}];
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{f-1}:0] fraction = x;
  wire [{f}:0] denominator = {f+1}'d{1 << f} + fraction;
  wire [{f+1}:0] rounded = ({2*f+3}'d{numerator} + (denominator >> 1)) / denominator;
  wire signed [{e}:0] result_exponent = {e+1}'d{2*bias-1} - exponent + rounded[{f+1}];
  wire special = exponent == {e}'d{maximum};
  wire [{width-2}:0] magnitude = exponent == 0 ? {width-1}'h{infinity:x} :
      (special || result_exponent <= 0) ? {width-1}'d0 :
      result_exponent * {width-1}'d{1 << f} + rounded[{f-1}:0];
  assign y = special && fraction ? {width}'h{quiet_nan:x} : {{sign_in, magnitude}};
endmodule
'''


def emit_binary_sqrt(exponent_width: int, fraction_width: int, detail: str) -> str:
    """Binary square root using a bounded monotone root-prefix recurrence.

    Only the normalized significand is squared. Integer radicands cannot be
    exactly midway between roots, because (r+1/2)**2 has fractional part 1/4.
    Hence radicand-r*r > r is the exact nearest-even rounding condition.
    """
    if exponent_width < 3 or fraction_width < 1:
        raise ValueError('binary sqrt needs exponent width >= 3 and a fraction')
    e, f = exponent_width, fraction_width
    width, bias = 1 + e + f, (1 << (e-1))-1
    maximum = (1 << e)-1
    infinity = maximum << f
    quiet_nan = infinity | (1 << (f-1))
    return f'''// {detail}
// Binary square root: bounded significand root and exact squared-midpoint RNE.
module top(input [{width-1}:0] x, output reg [{width-1}:0] y);
  wire sign_in = x[{width-1}];
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{f-1}:0] fraction = x;
  reg [{2*f+1}:0] radicand;
  reg [{f+1}:0] root;
  reg [{e}:0] output_exponent;
  integer bit_index;
  always @(*) begin
    radicand = ({2*f+2}'d{1 << f} + fraction) << ({f} + !exponent[0]);
    root = {f+2}'d{1 << f};
    bit_index = {f-1};
    repeat ({f}) begin
      root[bit_index] = 1'b1;
      if (root * root > radicand) root[bit_index] = 1'b0;
      bit_index = bit_index - 1;
    end
    root = root + (radicand - root * root > root);
    output_exponent = ((exponent + {e+1}'d{bias}) >> 1) + root[{f+1}];
    if (exponent == 0) y = {{sign_in, {width-1}'d0}};
    else if (sign_in || (exponent == {e}'d{maximum} && fraction)) y = {width}'h{quiet_nan:x};
    else if (exponent == {e}'d{maximum}) y = {width}'h{infinity:x};
    else y = output_exponent * {width}'d{1 << f} + root[{f-1}:0];
  end
endmodule
'''


def emit_binary_recip_power(exponent_width: int, fraction_width: int,
                           degree: int, detail: str) -> str:
    """Normalized reciprocal powers with one exact rounded quotient.

    The power-of-two numerator has no halfway quotient for the same reason
    as the reciprocal emitter. The hidden-bit carry handles the significand
    endpoint uniformly, and exponent arithmetic stays explicitly widened.
    """
    if exponent_width < 3 or fraction_width < 1 or degree not in (2, 3):
        raise ValueError('supported reciprocal powers are square and cube')
    e, f, p = exponent_width, fraction_width, degree
    width, bias = 1 + e + f, (1 << (e-1))-1
    maximum = (1 << e)-1
    infinity, nan = maximum << f, (maximum << f) | (1 << (f-1))
    denominator_width = p*(f+1)
    numerator_width = (p+1)*f + p + 2
    normalizer = (f"denominator <= {denominator_width}'d{1 << (p*f+1)} ? 2'd1 : "
                  + ("2'd2" if p == 2 else
                     f"denominator <= {denominator_width}'d{1 << (p*f+2)} ? 2'd2 : 2'd3"))
    sign_decl = f"  wire sign_in = x[{width-1}];\n" if p & 1 else ''
    signed_output = '{sign_in, magnitude}' if p & 1 else 'magnitude'
    return f'''// {detail}
// Reciprocal power: normalized integer significand power and exact RNE quotient.
module top(input [{width-1}:0] x, output [{width-1}:0] y);
{sign_decl}  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{f-1}:0] fraction = x;
  wire [{f}:0] significand = {f+1}'d{1 << f} + fraction;
  wire [{denominator_width-1}:0] denominator = significand ** {p};
  wire [1:0] normalize = {normalizer};
  wire [{f+1}:0] rounded = (({numerator_width}'d{1 << ((p+1)*f)} << normalize) +
      (denominator >> 1)) / denominator;
  wire signed [{e+2}:0] result_exponent = {e+3}'d{(p+1)*bias} - exponent * {e+3}'d{p} -
      normalize + rounded[{f+1}];
  wire special = exponent == {e}'d{maximum};
  wire [{width-2}:0] magnitude = exponent == 0 ? {width-1}'h{infinity:x} :
      (special || result_exponent <= 0) ? {width-1}'d0 :
      result_exponent >= {e+3}'d{maximum} ? {width-1}'h{infinity:x} :
      result_exponent * {width-1}'d{1 << f} + rounded[{f-1}:0];
  assign y = special && fraction ? {width}'h{nan:x} : {signed_output};
endmodule
'''


def emit_binary_root(exponent_width: int, fraction_width: int, degree: int,
                     inverse: bool, detail: str, precision: int | None = None) -> str:
    """Bounded normalized binary roots, with optional intermediate precision.

    Exponent division supplies a remainder for the significand scale. Both
    ordinary and inverse roots use a monotone bit-prefix search and compare
    the exact powered midpoint for rounding. An explicit precision parameter
    preserves algorithms that round to an intermediate binary format first.
    """
    if exponent_width < 3 or fraction_width < 1 or degree not in (2, 3):
        raise ValueError('supported binary roots are square and cube')
    e, f, d = exponent_width, fraction_width, degree
    precision = f if precision is None else precision
    if precision < f or precision > 32:
        raise ValueError('root precision must contain the output significand')
    p = precision
    width, bias = 1 + e + f, (1 << (e-1))-1
    maximum = (1 << e)-1
    infinity, nan = maximum << f, (maximum << f) | (1 << (f-1))
    work_width = d*(p+2) + f + 2
    scale = (f"{work_width}'d1 << ({d*p+f+d} - remainder)" if inverse else
             f"significand << ({d*p-f} + remainder)")
    exponent = '2 * ' + str(bias) + ' - exponent_quotient - 1' if inverse else 'exponent_quotient'
    power = 'value ** ' + str(d) + (' * significand' if inverse else '')
    second_round = ''
    final_name = 'root'
    if p > f:
        delta = p-f
        final_name = 'output_significand'
        second_round = f'''
    normalized_root = root >> root[{p+1}];
    output_significand = (normalized_root + {p+3}'d{(1 << (delta-1))-1} + normalized_root[{delta}]) >> {delta};
    result_exponent = result_exponent + output_significand[{f+1}];'''
    fraction_part = f'{final_name}[{f-1}:0]'
    zero_result = infinity if inverse else 0
    infinity_result = 0 if inverse else infinity
    nan_condition = 'exponent && (sign_in || (special && fraction))' if d == 2 else 'special && fraction'
    return f'''// {detail}
// Binary {'inverse ' if inverse else ''}{d}-root: exact powered-midpoint RNE, precision {p}.
module top(input [{width-1}:0] x, output [{width-1}:0] y);
  wire sign_in = x[{width-1}];
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{f-1}:0] fraction = x;
  wire [{f}:0] significand = {f+1}'d{1 << f} + fraction;
  wire special = exponent == {e}'d{maximum};
  wire [{e+1}:0] biased_exponent = exponent + {e+2}'d{(d-1)*bias};
  wire [{e+1}:0] exponent_quotient = biased_exponent / {d};
  wire [1:0] remainder = biased_exponent % {d};
  reg [{work_width-1}:0] numerator;
  reg [{p+1}:0] root;
  reg [{p+2}:0] normalized_root;
  reg [{f+1}:0] output_significand;
  reg [{e+1}:0] result_exponent;
  reg [{width-2}:0] magnitude;
  integer bit_index;
  function [{work_width-1}:0] powered;
    input [{p+2}:0] value;
    begin powered = {power}; end
  endfunction
  always @(*) begin
    numerator = {scale};
    root = {p+2}'d{1 << p};
    normalized_root = 0; output_significand = 0;
    bit_index = {p-1};
    repeat ({p}) begin
      root[bit_index] = 1'b1;
      root[bit_index] = powered(root) <= numerator;
      bit_index = bit_index - 1;
    end
    root = root + ((numerator << {d}) > powered((root << 1) + 1));
    result_exponent = {exponent} + root[{p+1}];{second_round}
    if (exponent == 0) magnitude = {width-1}'h{zero_result:x};
    else if (special) magnitude = {width-1}'h{infinity_result:x};
    else magnitude = result_exponent * {width-1}'d{1 << f} + {fraction_part};
  end
  assign y = {nan_condition} ? {width}'h{nan:x} : {{sign_in, magnitude}};
endmodule
'''

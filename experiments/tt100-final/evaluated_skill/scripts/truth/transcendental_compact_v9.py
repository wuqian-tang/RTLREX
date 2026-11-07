"""Typed word sharing for arithmetic floating-format kernels.

This structural optimizer preserves the existing numerical kernels and staged
rounding. It admits exact helper contracts, never filenames or truth answers.
Shared functions count source syntax, not physical arithmetic units.
"""
import re


def compact_transcendental_word_semantics(rtl: str) -> str:
    """Share 65-bit shifts, quotient field decode and signed dyadic reduction.

    Unsupported helper definitions or scopes fail closed. The signed quotient
    identity is valid for all signed64 values, including modular bias overflow.
    Arithmetic loop bodies are never globally rewritten into helper calls.
    """
    if any(token in rtl for token in ('`', '/*', 'task ', 'semantic_asr65')):
        return rtl
    port = re.search(r'module top\(input \[(\d+):0\] x, output(?: reg)? \[\d+:0\] y\);', rtl)
    if not port or not 1 <= int(port[1]) <= 62:
        return rtl
    functions = {m[1]: m[0] for m in re.finditer(r'  function(?: signed)?(?: \[\d+:0\])? (\w+);.*?  endfunction', rtl, re.S)}
    def compact(text):
        return re.sub(r'\s+', '', text)
    exact_ge = 'functionfp_ge;inputsigned[63:0]a,b;beginfp_ge=a>=b;endendfunction'
    exact_ge_shared = 'functionfp_ge;inputsigned[63:0]a,b;beginfp_ge=fp_le(b,a);endendfunction'
    exact_le = 'functionfp_le;inputsigned[63:0]a,b;beginfp_le=a<=b;endendfunction'
    ge = compact(functions.get('fp_ge', ''))
    if ge not in (exact_ge, exact_ge_shared) or (ge == exact_ge_shared and compact(functions.get('fp_le','')) != exact_le):
        return rtl
    add = compact(functions.get('fp_add', ''))
    allowed_add = ('functionsigned[63:0]fp_add;inputsigned[63:0]a,b;beginfp_add=a+b;endendfunction',
                   'functionsigned[63:0]fp_add;inputsigned[63:0]a,b;beginfp_add=semantic_add65(a,b);endendfunction')
    if add not in allowed_add:
        return rtl
    if 'semantic_add65' in add and compact(functions.get('semantic_add65','')) != 'functionsigned[64:0]semantic_add65;inputsigned[64:0]a,b;beginsemantic_add65=a+b;endendfunction':
        return rtl
    sub = compact(functions.get('fp_sub',''))
    if sub not in ('functionsigned[63:0]fp_sub;inputsigned[63:0]a,b;beginfp_sub=a-b;endendfunction',
                   'functionsigned[63:0]fp_sub;inputsigned[63:0]a,b;beginfp_sub=fp_add(a,-b);endendfunction'):
        return rtl
    rne = functions.get('semantic_rne64','')
    expected = ('functionsigned[63:0]semantic_rne64;inputsigned[63:0]value;input[5:0]shift;inputsigned[64:0]bias;'
                'regsigned[64:0]extended;beginextended=value;extended=semantic_add65(extended,bias);'
                'extended=semantic_add65(extended,value[shift]);semantic_rne64=extended>>>shift;endendfunction')
    if compact(rne) != expected:
        return rtl
    result = rtl.replace(rne, rne.replace('value[shift]', 'semantic_quotient_parity(value, shift)').replace('extended >>> shift', 'semantic_asr65(extended, shift)'))
    right = functions.get('fp_asr','')
    if right:
        if compact(right) != 'functionsigned[63:0]fp_asr;inputsigned[63:0]a,b;beginfp_asr=a>>>b;endendfunction':
            return rtl
        result = result.replace(right, right.replace('a >>> b', 'semantic_asr65(a, b)'))
    helpers = '''
  // Signed65 arithmetic shift; signed64 callers are exactly sign extended.
  function signed [64:0] semantic_asr65;
    input signed [64:0] value;
    input [63:0] shift;
    begin semantic_asr65 = value >>> shift; end
  endfunction
  function semantic_quotient_parity;
    input signed [63:0] value;
    input [63:0] shift;
    begin semantic_quotient_parity = semantic_asr65(value, shift); end
  endfunction
'''
    result = result[:port.end()] + helpers + result[port.end():]
    # Unsigned primary-word fields are exact projections of a word quotient.
    declarations = {}
    for m in re.finditer(r'\bwire(?: \[(\d+):0\])? (\w+) = x(?:\[(\d+)(?::(\d+))?\])?;', result):
        width = int(m[1])+1 if m[1] else 1
        lo = int(m[4] or m[3]) if m[3] else 0
        hi = int(m[3]) if m[3] else width-1
        if hi-lo+1 != width or hi > int(port[1]):
            continue
        declarations[m[2]] = width
        if lo == int(port[1]) and width == 1:
            result = result.replace(m[0], f"wire {m[2]} = fp_ge(x, 64'd{1 << lo});")
        elif lo:
            geometry = f'[{width-1}:0] ' if width > 1 else ''
            result = result.replace(m[0], f'wire {geometry}{m[2]} = semantic_asr65(x, {lo});')
    # Helper inputs are signed64, so unsigned fields zero-extend positively.
    for name,width in declarations.items():
        if width >= 63:
            continue
        result = result.replace(f"fp_sub($signed({{1'b0,{name}}}),", f'fp_sub({name},')
        result = re.sub(r'fp_ge\(\{1\x27b1,\s*'+re.escape(name)+r'\},', f"fp_ge(fp_add(64'd{1 << width}, {name}),", result)
    mux = compact(functions.get('fp_mux',''))
    expected_mux = ('functionsigned[63:0]fp_mux;inputsigned[63:0]condition;inputsigned[63:0]a,b;'
                    'beginfp_mux=condition?a:b;endendfunction')
    if mux == expected_mux:
        result = re.sub(r'if \((\w+)\)\s*\n\s*(\w+) = \(-\2\);', r'\2 = fp_mux(\1, fp_sub(0, \2), \2);', result)
        normal = re.compile(r'if \(fp_ge\((\w+), (\w+)\)\) begin\s*bin_exp = (\w+);\s*shift = (\d+);\s*end else begin\s*bin_exp = fp_sub\(\3, 1\);\s*shift = (\d+);\s*end')
        def normalize(m):
            if int(m[4]) != int(m[5])+1 or not 1 <= int(m[5]) < 63:
                return m[0]
            return f'bin_exp = fp_mux(fp_ge({m[1]}, {m[2]}), {m[3]}, fp_sub({m[3]}, 1));\n      shift = fp_add({m[5]}, fp_ge({m[1]}, {m[2]}));'
        result = normal.sub(normalize,result)
        qnormal = re.compile(r'if \(fp_ge\((\w+), (\w+)\)\) begin\s*normq = \1;\s*bin_exp = (\w+);\s*end else begin\s*normq = fp_asl\(\1, 1\);\s*bin_exp = fp_sub\(\3, 1\);\s*end')
        if compact(functions.get('fp_asl','')) != 'functionsigned[63:0]fp_asl;inputsigned[63:0]a,b;beginfp_asl=a<<<b;endendfunction':
            return rtl
        result = qnormal.sub(lambda m: f'normq = fp_mux(fp_ge({m[1]}, {m[2]}), {m[1]}, fp_asl({m[1]}, 1));\n      bin_exp = fp_mux(fp_ge({m[1]}, {m[2]}), {m[3]}, fp_sub({m[3]}, 1));', result)
        # A pure combinational numerical kernel may run on exceptional inputs:
        # its result is masked by the unchanged field predicates. No guard is
        # dropped, and no staged RNE or underflow branch is changed.
        ieee = re.compile(r'if \(fp_eq\((\w+), (\d+\x27h[0-9a-f]+)\)\) begin\s*'
            r'if \(fp_ne\((\w+), 0\)\)\s*y = (\d+\x27h[0-9a-f]+);\s*'
            r'else if \((\w+)\)\s*y = (\d+\x27h[0-9a-f]+);\s*'
            r'else\s*y = (\d+\x27h[0-9a-f]+);\s*end else if \(fp_eq\(\1, 0\)\) begin\s*'
            r'y = (\d+\x27h[0-9a-f]+);\s*end else begin\s*(.*)\s*end\s*end\s*endmodule\s*$', re.S)
        matched = ieee.search(result)
        # Only side-effect-free functions and a single combinational block.
        pure = len(re.findall(r'\balways\b', result)) == 1 and not re.search(r'\binitial\b|\$((?!signed\b|unsigned\b)\w+)', result)
        for definition in functions.values():
            variables = set(re.findall(r'\b(?:input|reg|integer)\s+(?:signed\s+)?(?:\[\d+:0\]\s*)?(\w+)', definition))
            for declaration in re.finditer(r'\b(?:input|reg|integer)\b[^;]*;', definition):
                text = re.sub(r'\b(?:input|reg|integer|signed)\b|\[\d+:0\]', '', declaration[0]).strip('; ')
                variables.update(name.strip() for name in text.split(','))
            name = re.search(r'function(?: signed)?(?: \[\d+:0\])? (\w+);', definition)[1]
            variables.add(name)
            writes = re.findall(r'\b(\w+)\s*=(?!=)', definition)
            pure = pure and set(writes) <= variables
        if matched and pure and matched[1] in declarations and matched[3] in declarations and matched[5] in declarations:
            replacement = (matched[9] + '\n      y = fp_mux(fp_eq(' + matched[1] + ', 0), ' + matched[8] + ', y);\n'
                '      y = fp_mux(fp_eq(' + matched[1] + ', ' + matched[2] + '), fp_mux(fp_ne(' + matched[3] + ', 0), '
                + matched[4] + ', fp_mux(' + matched[5] + ', ' + matched[6] + ', ' + matched[7] + ')), y);\n'
                '  end\nendmodule\n')
            result = result[:matched.start()] + replacement
        division = compact(functions.get('fp_div',''))
        if division == 'functionsigned[63:0]fp_div;inputsigned[63:0]a,b;beginfp_div=a/b;endendfunction':
            constants = {m[1]:int(m[2]) for m in re.finditer(r'localparam signed \[63:0\] (\w+)\s*=\s*64\x27sd(\d+);', result)}
            reduction = re.compile(r'if \(fp_ge\((\w+), 0\)\)\s*(\w+) = fp_div\(\(fp_add\(\1, (\w+)\)\), (\w+)\);\s*else\s*\2 = fp_div\(\(fp_sub\(\1, \3\)\), \4\);')
            def reduce(m):
                power = constants.get(m[4],0)
                half = constants.get(m[3],0)
                if not 2 <= power <= 1 << 62 or power & (power-1) or half != power//2:
                    return m[0]
                shift = power.bit_length()-1
                return (f'{m[2]} = fp_add({m[1]}, fp_mux(fp_ge({m[1]}, 0), {m[3]}, fp_sub(0, {m[3]})));\n'
                        f'      {m[2]} = semantic_asr65(fp_add({m[2]}, fp_mux(fp_ge({m[2]}, 0), 0, 64\'sd{power-1})), {shift});')
            result = reduction.sub(reduce,result)
            without = result.replace(functions['fp_div'],'')
            if not re.search(r'\bfp_div\s*\(',without):
                result = without
    return result

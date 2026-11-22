"""Keep bounded normalization loops in their original word representation.

The helper-sharing pass remains active outside each loop. Yosys unrolls loop
bodies; inserting nested function calls there needlessly replicates function
scope names and elaboration work. No filename, truth address, or metric input
is inspected. Unsupported loop syntax conservatively leaves the source intact.
"""
import re
from truth.fixed_point_compact import compact_fixed_point_operators


def compact_outside_word_loops(rtl, width=64, body_start=None,
                             min_word_operator_uses=1):
    marker = '  always @(*) begin'
    if marker not in rtl:
        return rtl
    header,body = rtl.split(marker,1)
    clean = re.sub(r'//[^\n]*|/\*.*?\*/',lambda m:' '*len(m[0]),body,flags=re.S)
    loops = list(re.finditer(r'\bfor\s*\([^)]*\)',clean))
    regions=[]
    previous_end=0
    for loop in loops:
        if loop.start()<previous_end:
            return rtl
        # The established normalized fixed-point word emitters use an if/begin
        # body. Unrecognized constructs get the unfactored safe representation.
        tail=clean[loop.end():]
        match=re.match(r'\s*if\s*\([^)]*\)\s*begin\b',tail)
        if not match:
            return rtl
        start=loop.end()+match.end()
        depth=1
        end=None
        for token in re.finditer(r'\bbegin\b|\bend\b',clean[start:]):
            depth+=1 if token[0]=='begin' else -1
            if depth==0:
                end=start+token.end();break
        if end is None:
            return rtl
        regions.append((loop.start(),end,body[loop.start():end]))
        previous_end=end
    if not regions:
        return compact_fixed_point_operators(rtl,width=width,body_start=body_start,
                         min_word_operator_uses=min_word_operator_uses)
    for number,(start,end,original) in reversed(list(enumerate(regions))):
        body=body[:start]+f'/* PRESERVED_WORD_LOOP_{number} */'+body[end:]
    changed=compact_fixed_point_operators(header+marker+body,width=width,body_start=body_start,
                         min_word_operator_uses=min_word_operator_uses)
    for number,(_,_,original) in enumerate(regions):
        placeholder=f'/* PRESERVED_WORD_LOOP_{number} */'
        if changed.count(placeholder)!=1:
            return rtl
        changed=changed.replace(placeholder,original)
    return changed

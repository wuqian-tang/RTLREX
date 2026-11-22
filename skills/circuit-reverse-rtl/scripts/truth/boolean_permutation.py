"""Exact input-permutation equivalence of output Boolean functions.

Every match is checked over the complete supplied domain. The resulting
function calls reuse source syntax, not necessarily physical logic. This is a
low-level Boolean fallback and is never evidence of word-level recovery.
"""
from __future__ import annotations
from collections import Counter
from itertools import islice
from typing import Sequence
from .boolean_fallback import _bit_tables, _validate_table


def _signatures(table: Sequence[int], n_inputs: int) -> list[tuple]:
    count = 1 << n_inputs
    mask = (1 << count) - 1
    packed = bytes(sum(table[start + bit] << bit for bit in range(8)
                       if start + bit < count) for start in range(0, count, 8))
    bits = int.from_bytes(packed, 'little')
    low_masks = [mask // ((1 << (1 << variable)) + 1) for variable in range(n_inputs)]
    def flip(values: int, variable: int) -> int:
        step = 1 << variable
        low = low_masks[variable]
        return ((values & low) << step) | ((values >> step) & low)
    signatures = []
    for variable in range(n_inputs):
        derivative = bits ^ flip(bits, variable)
        pair_influences = sorted((derivative ^ flip(derivative, other)).bit_count()
                                 for other in range(n_inputs) if other != variable)
        signatures.append((derivative.bit_count(),
                           table[1 << variable] ^ table[0],
                           table[(count - 1) ^ (1 << variable)] ^ table[count - 1],
                           tuple(pair_influences)))
    return signatures


def _matches(base: Sequence[int], target: Sequence[int], permutation: Sequence[int],
             complement: int) -> bool:
    # permutation[source input position] is the corresponding base position.
    indices = [0]
    for bit in permutation:
        indices += [index | (1 << bit) for index in indices]
    return all(target[index] == (base[base_index] ^ complement)
               for index, base_index in enumerate(indices))


def find_output_permutations(n_inputs: int, n_outputs: int, words: Sequence[int]):
    """Return representative output bits and fully checked output mappings."""
    _validate_table(n_inputs, n_outputs, words)
    tables = _bit_tables(words, n_outputs)
    signatures = [_signatures(table, n_inputs) for table in tables]
    representatives: list[int] = []
    mappings: list[tuple[int, tuple[int, ...], int]] = []
    identity = tuple(range(n_inputs))
    for output, target_signature in enumerate(signatures):
        match = None
        for group, representative in enumerate(representatives):
            base_signature = signatures[representative]
            if Counter(target_signature) != Counter(base_signature):
                continue
            base, target = tables[representative], tables[output]
            complement = target[0] ^ base[0]
            options = [tuple(bit for bit, signature in enumerate(base_signature)
                             if signature == target_signature[source])
                       for source in range(n_inputs)]
            # Unique derivative signatures yield a direct general permutation.
            candidates = []
            if all(len(option) == 1 for option in options):
                candidates.append(tuple(option[0] for option in options))
            # Repeated signatures are common in symmetric/rotational circuits.
            # First test generic cyclic and reflected input orders, then a
            # bounded general backtracking enumeration constrained by probes.
            candidates.extend(tuple((source + shift) % n_inputs for source in range(n_inputs))
                              for shift in range(n_inputs))
            candidates.extend(tuple((shift - source) % n_inputs for source in range(n_inputs))
                              for shift in range(n_inputs))
            def enumerate_permutations():
                assigned = {}
                used = set()
                search_order = sorted(range(n_inputs), key=lambda source: (len(options[source]), source))
                visited = 0
                def visit(depth):
                    nonlocal visited
                    visited += 1
                    if visited > 4096:
                        return
                    if depth == n_inputs:
                        yield tuple(assigned[source] for source in range(n_inputs))
                        return
                    source = search_order[depth]
                    for bit in options[source]:
                        if bit in used:
                            continue
                        if any((target[(1 << source) | (1 << other)] ^ complement)
                               != base[(1 << bit) | (1 << mapped)]
                               for other, mapped in assigned.items()):
                            continue
                        assigned[source] = bit; used.add(bit)
                        yield from visit(depth + 1)
                        used.remove(bit); del assigned[source]
                yield from visit(0)
            candidates.extend(islice(enumerate_permutations(), 32))
            for permutation in dict.fromkeys(candidates):
                if any(base_signature[bit] != target_signature[source]
                       for source, bit in enumerate(permutation)):
                    continue
                if _matches(base, target, permutation, complement):
                    match = (group, permutation, complement)
                    break
            if match is not None:
                break
        if match is None:
            match = (len(representatives), identity, 0)
            representatives.append(output)
        mappings.append(match)
    return representatives, mappings


def permutation_argument(permutation: Sequence[int]) -> str:
    """Spell a bit permutation with maximally shared contiguous input slices."""
    count = len(permutation)
    if count < 1 or sorted(permutation) != list(range(count)):
        raise ValueError("input mapping must be a complete bit permutation")
    inverse = [0] * count
    for source, target in enumerate(permutation):
        inverse[target] = source
    if inverse == list(range(count)):
        return 'x'
    bits = list(reversed(inverse))
    pieces = []
    cursor = 0
    while cursor < len(bits):
        end = cursor + 1
        while end < len(bits) and bits[end] == bits[end - 1] - 1:
            end += 1
        first, last = bits[cursor], bits[end - 1]
        pieces.append(f'x[{first}]' if first == last else f'x[{first}:{last}]')
        cursor = end
    return pieces[0] if len(pieces) == 1 else '{' + ','.join(pieces) + '}'


def reusable_function_within_budget(core: str, mappings: Sequence[tuple], *,
                                    max_statements: int = 4096,
                                    max_expanded_statements: int = 32768) -> bool:
    """Bound procedural-function elaboration/replay before reuse is admitted.

    A function's scalar DAG is copied for every distinct argument permutation
    by the fixed Verilog frontend. Procedural scratch aliases can retain X bits
    and require exhaustive simulation rather than bit-parallel replay; large
    repeated scopes then cost substantially more than a flat scalar DAG.
    These fixed work bounds govern representation construction, never pricing,
    truth matching, solver deadlines, or high-level classification. Zero lets
    callers explicitly request the always-available flat structural candidates.
    """
    import re
    if any(type(limit) is not int or limit < 0
           for limit in (max_statements, max_expanded_statements)):
        raise ValueError('function work bounds must be nonnegative integers')
    statements = len(re.findall(r'(?m)^\s*assign\b', core))
    calls = len({tuple(permutation) for _, permutation, _ in mappings})
    return (statements <= max_statements
            and statements * calls <= max_expanded_statements)


def emit_reusable_function(n_inputs: int, n_outputs: int, core: str,
                            representatives: Sequence[int], mappings: Sequence[tuple]) -> str:
    """Package an independently emitted scalar DAG as a pure RTL function."""
    width = len(representatives)
    body = core.split(');', 1)[1].rsplit('endmodule', 1)[0]
    declarations, assignments = [], []
    for statement in body.split(';'):
        statement = statement.strip()
        if not statement:
            continue
        if statement.startswith('wire '):
            declarations.append('    reg ' + statement[5:] + ';')
        elif statement.startswith('assign '):
            statement = statement[7:].replace('x[', 'z[').replace('y[', 'bf0[')
            assignments.append('      ' + statement + ';')
        else:
            raise ValueError('function core contains non-DAG syntax')
    buckets: dict[tuple[int, ...], list[tuple[int, int, int]]] = {}
    for output, (group, permutation, complement) in enumerate(mappings):
        buckets.setdefault(tuple(permutation), []).append((output, group, complement))
    lines = ['// Exact truth-derived reusable structural Boolean function; not high-level RTL.',
             '// Source reuse across input permutations does not claim physical sharing.',
             f'module top(input [{n_inputs - 1}:0] x, output [{n_outputs - 1}:0] y);',
             f'  function [{width - 1}:0] bf0;', f'    input [{n_inputs - 1}:0] z;']
    lines.extend(declarations)
    lines.extend(['    begin', *assignments, '    end', '  endfunction'])
    for index, (permutation, outputs) in enumerate(buckets.items()):
        outputs.sort()
        argument = permutation_argument(permutation)
        contiguous = (len(outputs) == width and all(group == position and not complement
                      for position, (_, group, complement) in enumerate(outputs))
                      and all(output == outputs[0][0] + position
                              for position, (output, _, _) in enumerate(outputs)))
        if contiguous:
            low, high = outputs[0][0], outputs[-1][0]
            lhs = f'y[{low}]' if width == 1 else f'y[{high}:{low}]'
            lines.append(f'  assign {lhs} = bf0({argument});')
        else:
            lines.append(f'  wire [{width - 1}:0] q{index};')
            lines.append(f'  assign q{index} = bf0({argument});')
            for output, group, complement in outputs:
                inverse = '~' if complement else ''
                lines.append(f'  assign y[{output}] = {inverse}q{index}[{group}];')
    lines.extend(('endmodule', ''))
    return '\n'.join(lines)

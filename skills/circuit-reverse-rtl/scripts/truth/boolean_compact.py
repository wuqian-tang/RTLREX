"""Truth-derived Boolean DAG sharing and bounded variable-order exploration.

The emitted scalar network exposes all structure; there are no case tables,
ROMs, literal truth vectors, address-specific corrections or trained answers.
These emitters are Boolean fallbacks, never high-level RTL recognizers.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

from .boolean_fallback import _bit_tables, _scalar_declarations, _validate_table


def _orders(n_in: int, words: Sequence[int]) -> list[tuple[int, ...]]:
    ascending = tuple(range(n_in))
    # Total output-bit influence is measured only on the supplied function.
    influence = []
    for bit in range(n_in):
        step = 1 << bit
        influence.append(sum((words[index] ^ words[index | step]).bit_count()
                             for index in range(len(words)) if not index & step))
    descending_influence = tuple(sorted(ascending, key=lambda b: (-influence[b], b)))
    half = (n_in + 1) // 2
    interleaved = tuple(bit for pair in zip(range(half), range(half, n_in)) for bit in pair)
    endpoints = tuple(bit for pair in zip(range(half), reversed(range(half, n_in))) for bit in pair)
    if n_in % 2:
        interleaved += (half - 1,)
        endpoints += (half - 1,)
    candidates = (ascending, ascending[::-1], descending_influence,
                  descending_influence[::-1], interleaved, interleaved[::-1],
                  endpoints, endpoints[::-1])
    return list(dict.fromkeys(candidates))


def emit_compact_robdd(n_in: int, n_out: int, words: Sequence[int],
                       order: Sequence[int]) -> tuple[str, int]:
    """Canonical complement-edge DAG with shared selects and complements."""
    _validate_table(n_in, n_out, words)
    order = tuple(order)
    if sorted(order) != list(range(n_in)):
        raise ValueError("BDD order must contain each input variable exactly once")
    indices = [0]
    for variable in order:
        indices += [index | (1 << variable) for index in indices]
    reordered = [words[index] for index in indices]
    nodes: list[tuple[int, int, int]] = []
    unique: dict[tuple[int, int, int], int] = {}

    @lru_cache(maxsize=None)
    def build(values: bytes, depth: int) -> int:
        first = values[0]
        if values.count(first) == len(values):
            return -1 if first else 0
        if first:
            return ~build(bytes(value ^ 1 for value in values), depth)
        low = build(values[0::2], depth + 1)
        high = build(values[1::2], depth + 1)
        if low == high:
            return low
        key = (order[depth], low, high)
        if key not in unique:
            unique[key] = len(nodes) + 1
            nodes.append(key)
        return unique[key]

    roots = [build(bytes(table), 0) for table in _bit_tables(reordered, n_out)]
    # Each repeated complemented edge is computed once, rather than spelling
    # the same inversion in every fanout. Leaf decision nodes reduce to inputs.
    negative_uses = Counter(edge for _, low, high in nodes for edge in (low, high)
                            if edge < -1)
    negative_uses.update(edge for edge in roots if edge < -1)
    inversions = {~edge for edge, count in negative_uses.items() if count > 1}
    leaf_nodes = {node: variable for node, (variable, low, high)
                  in enumerate(nodes, 1) if low == 0 and high == -1}

    def positive(edge: int) -> str:
        return f"i{leaf_nodes[edge]}" if edge in leaf_nodes else f"n{edge}"

    def ref(edge: int) -> str:
        if edge == 0:
            return "1'b0"
        if edge == -1:
            return "1'b1"
        if edge > 0:
            return positive(edge)
        return f"c{~edge}" if ~edge in inversions else "~" + positive(~edge)

    lines = ["// Exact shared structural Boolean DAG; not high-level RTL.",
             "// Input selects and multiply-used complemented edges are shared.",
             f"module top(input [{n_in - 1}:0] x, output [{n_out - 1}:0] y);"]
    used_inputs = sorted({variable for variable, _, _ in nodes})
    lines.extend(_scalar_declarations("i", used_inputs))
    lines.extend(_scalar_declarations("n", [node for node in range(1, len(nodes) + 1)
                                           if node not in leaf_nodes]))
    if inversions:
        names = [f"c{node}" for node in sorted(inversions)]
        lines.extend("  wire " + ",".join(names[start:start + 64]) + ";"
                     for start in range(0, len(names), 64))
    for variable in used_inputs:
        lines.append(f"  assign i{variable} = x[{variable}];")
    for node, (variable, low, high) in enumerate(nodes, 1):
        if node not in leaf_nodes:
            lines.append(f"  assign n{node} = i{variable} ? {ref(high)} : {ref(low)};")
        if node in inversions:
            lines.append(f"  assign c{node} = ~{positive(node)};")
    for output, root in enumerate(roots):
        lines.append(f"  assign y[{output}] = {ref(root)};")
    lines.extend(("endmodule", ""))
    build.cache_clear()
    return "\n".join(lines), len(nodes) - len(leaf_nodes)


def emit_plain_robdd(n_in: int, n_out: int, words: Sequence[int],
                     order: Sequence[int]) -> tuple[str, int]:
    """Ordinary shared BDD: a complementary cofactor can use a shared mux.

    Complement-edge DAGs minimize node count but sometimes add many explicit
    source inversions. This equally exact candidate retains distinct cofactors
    and lets the unchanged syntax metric choose the better representation.
    """
    _validate_table(n_in, n_out, words)
    order = tuple(order)
    if sorted(order) != list(range(n_in)):
        raise ValueError("BDD order must contain each input variable exactly once")
    indices = [0]
    for variable in order:
        indices += [index | (1 << variable) for index in indices]
    reordered = [words[index] for index in indices]
    nodes: list[tuple[int, int, int]] = []
    unique: dict[tuple[int, int, int], int] = {}
    @lru_cache(maxsize=None)
    def build(values: bytes, depth: int) -> int:
        if values.count(values[0]) == len(values):
            return int(values[0])
        low = build(values[0::2], depth + 1)
        high = build(values[1::2], depth + 1)
        if low == high:
            return low
        key = (order[depth], low, high)
        if key not in unique:
            unique[key] = len(nodes) + 2
            nodes.append(key)
        return unique[key]
    roots = [build(bytes(table), 0) for table in _bit_tables(reordered, n_out)]
    leaf_nodes = {node: variable for node, (variable, low, high)
                  in enumerate(nodes, 2) if low == 0 and high == 1}
    def ref(edge: int) -> str:
        if edge < 2:
            return f"1'b{edge}"
        return f"i{leaf_nodes[edge]}" if edge in leaf_nodes else f"n{edge}"
    used_inputs = sorted({variable for variable, _, _ in nodes})
    lines = ["// Exact shared structural Boolean DAG; not high-level RTL.",
             "// Distinct cofactors share decision nodes without implicit inversions.",
             f"module top(input [{n_in - 1}:0] x, output [{n_out - 1}:0] y);"]
    lines.extend(_scalar_declarations("i", used_inputs))
    lines.extend(_scalar_declarations("n", [node for node in range(2, len(nodes) + 2)
                                           if node not in leaf_nodes]))
    lines.extend(f"  assign i{variable} = x[{variable}];" for variable in used_inputs)
    for node, (variable, low, high) in enumerate(nodes, 2):
        if node not in leaf_nodes:
            lines.append(f"  assign n{node} = i{variable} ? {ref(high)} : {ref(low)};")
    lines.extend(f"  assign y[{output}] = {ref(root)};" for output, root in enumerate(roots))
    lines.extend(("endmodule", ""))
    build.cache_clear()
    return "\n".join(lines), len(nodes) - len(leaf_nodes)


def emit_factored_anf(n_in: int, n_out: int, words: Sequence[int]) -> tuple[str, int]:
    """Share recurring monomial factors and balanced XOR subexpressions."""
    _validate_table(n_in, n_out, words)
    functions = []
    for coefficients in _bit_tables(words, n_out):
        for bit in range(n_in):
            step = 1 << bit
            for term in range(1 << n_in):
                if term & step:
                    coefficients[term] ^= coefficients[term ^ step]
        functions.append([term for term, coefficient in enumerate(coefficients) if coefficient])
    assignments: list[str] = []
    factors: dict[int, str] = {0: "1'b1"}
    factors.update({1 << bit: f"i{bit}" for bit in range(n_in)})
    xor_nodes: dict[tuple[str, str], str] = {}

    def factor(term: int) -> str:
        if term not in factors:
            # A deterministic prefix chain shares factors across all outputs.
            bit = 1 << (term.bit_length() - 1)
            left, right = factor(term ^ bit), factor(bit)
            name = f"a{len(assignments)}"
            factors[term] = name
            assignments.append(f"  assign {name} = {left} & {right};")
        return factors[term]

    def xor(terms: Sequence[str]) -> str:
        if not terms:
            return "1'b0"
        if len(terms) == 1:
            return terms[0]
        middle = len(terms) // 2
        key = tuple(sorted((xor(terms[:middle]), xor(terms[middle:]))))
        if key not in xor_nodes:
            name = f"a{len(assignments)}"
            xor_nodes[key] = name
            assignments.append(f"  assign {name} = {key[0]} ^ {key[1]};")
        return xor_nodes[key]

    roots = [xor([factor(term) for term in terms]) for terms in functions]
    lines = ["// Exact shared and factored structural ANF; not high-level RTL.",
             f"module top(input [{n_in - 1}:0] x, output [{n_out - 1}:0] y);"]
    used_inputs = sorted({bit for terms in functions for term in terms
                          for bit in range(n_in) if term & (1 << bit)})
    lines.extend(_scalar_declarations("i", used_inputs))
    lines.extend(_scalar_declarations("a", range(len(assignments))))
    lines.extend(f"  assign i{bit} = x[{bit}];" for bit in used_inputs)
    lines.extend(assignments)
    lines.extend(f"  assign y[{bit}] = {root};" for bit, root in enumerate(roots))
    lines.extend(("endmodule", ""))
    return "\n".join(lines), len(assignments)


def choose_compact_boolean(n_in: int, n_out: int,
                           words: Sequence[int], *,
                           max_function_statements: int = 4096,
                           max_function_expanded_statements: int = 32768) -> tuple[str, str, int]:
    """Choose bounded, complete-truth-derived candidates under package pricing.

    Plain and complement-edge BDDs, ANF factoring and input-permutation reuse
    all remain structural Boolean fallbacks. Complete matching is mandatory
    before the reusable-function candidate exists. Source cost is the package
    calculator's result; no weights, widths or representation labels change.
    """
    from cost.RTL_cost_calculator import evaluate_rtl
    from .boolean_fallback import emit_shared_anf
    from .boolean_permutation import (find_output_permutations, emit_reusable_function,
                                      reusable_function_within_budget)
    if any(type(limit) is not int or limit < 0 for limit in
           (max_function_statements, max_function_expanded_statements)):
        raise ValueError("function work bounds must be nonnegative integers")
    best = None
    with TemporaryDirectory(prefix="boolean-candidates-") as directory:
        path = Path(directory) / "candidate.v"
        def consider(family: str, source: str, nodes: int):
            nonlocal best
            path.write_text(source)
            score = evaluate_rtl(str(path))[0]
            item = (score, len(source), nodes, family, source)
            if best is None or item[:3] < best[:3]:
                best = item
        orders = _orders(n_in, words)
        for order in orders:
            for emitter in (emit_compact_robdd, emit_plain_robdd):
                source, nodes = emitter(n_in, n_out, words, order)
                consider("shared ROBDD fallback", source, nodes)
        source, nodes = emit_factored_anf(n_in, n_out, words)
        consider("structural ANF fallback", source, nodes)
        # Retain the original exact ANF emitter when factoring is not useful
        # under the caller's unchanged selected cost CSV.
        source, nodes = emit_shared_anf(n_in, n_out, words)
        consider("structural ANF fallback", source, nodes)
        representatives, mappings = find_output_permutations(n_in, n_out, words)
        if len(representatives) < n_out:
            packed = [sum(((word >> bit) & 1) << index
                          for index, bit in enumerate(representatives)) for word in words]
            for order in _orders(n_in, packed):
                for emitter in (emit_compact_robdd, emit_plain_robdd):
                    core, nodes = emitter(n_in, len(representatives), packed, order)
                    if not reusable_function_within_budget(
                            core, mappings, max_statements=max_function_statements,
                            max_expanded_statements=max_function_expanded_statements):
                        continue
                    source = emit_reusable_function(n_in, n_out, core, representatives, mappings)
                    consider("shared ROBDD fallback", source, nodes)
    assert best is not None
    _, _, nodes, family, source = best
    return family, source, nodes

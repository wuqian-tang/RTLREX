"""Exact structural Boolean fallbacks for complete truth tables.

These emitters preserve all table entries but do not claim word-level recovery.
They are deliberately opt-in so a successful low-level fallback cannot be
confused with a recovered high-level RTL result.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Sequence, Tuple


def _scalar_declarations(prefix: str, indices: range) -> List[str]:
    # Scalars preserve the actual Boolean-node width in both the frontend and
    # source cost analysis. Grouping declarations limits line length.
    names = [f"{prefix}{index}" for index in indices]
    return ["  wire " + ",".join(names[start:start + 64]) + ";"
            for start in range(0, len(names), 64)]


def _balanced_xor(operands: Sequence[str]) -> str:
    # Avoid a linear-depth expression tree for dense ANF outputs.
    if not operands:
        return "1'b0"
    if len(operands) == 1:
        return operands[0]
    middle = len(operands) // 2
    return "(" + _balanced_xor(operands[:middle]) + " ^ " + _balanced_xor(operands[middle:]) + ")"


def _validate_table(n_in: int, n_out: int, words: Sequence[int]) -> None:
    if type(n_in) is not int or type(n_out) is not int or n_in < 1 or n_out < 1:
        raise ValueError("truth interface widths must be positive integers")
    if len(words) != 1 << n_in:
        raise ValueError("complete truth domain does not match input width")
    if any(not isinstance(word, int) or word < 0 or word >= 1 << n_out for word in words):
        raise ValueError("truth output word is outside its unsigned width")


def _bit_tables(words: Sequence[int], n_out: int) -> List[bytearray]:
    return [bytearray((word >> bit) & 1 for word in words) for bit in range(n_out)]


def emit_shared_anf(n_in: int, n_out: int, words: Sequence[int]) -> Tuple[str, int]:
    """Return Verilog and the number of shared algebraic-normal-form monomials."""

    _validate_table(n_in, n_out, words)
    functions: List[List[int]] = []
    shared: set[int] = set()
    for coefficients in _bit_tables(words, n_out):
        for bit in range(n_in):
            step = 1 << bit
            for term in range(1 << n_in):
                if term & step:
                    coefficients[term] ^= coefficients[term ^ step]
        terms = [term for term, coefficient in enumerate(coefficients) if coefficient]
        functions.append(terms)
        shared.update(terms)

    monomials = sorted(shared)
    index = {term: idx for idx, term in enumerate(monomials)}
    lines = [
        "// Exact truth-derived structural ANF fallback.",
        "// This low-level Boolean representation is not classified as high-level RTL.",
        f"module top(input [{n_in - 1}:0] x, output [{n_out - 1}:0] y);",
    ]
    if monomials:
        lines.extend(_scalar_declarations("m", range(len(monomials))))
    for term in monomials:
        rhs = "1'b1" if term == 0 else " & ".join(
            f"x[{bit}]" for bit in range(n_in) if term & (1 << bit)
        )
        lines.append(f"  assign m{index[term]} = {rhs};")
    for output, terms in enumerate(functions):
        rhs = _balanced_xor([f"m{index[term]}" for term in terms])
        lines.append(f"  assign y[{output}] = {rhs};")
    lines.extend(("endmodule", ""))
    return "\n".join(lines), len(monomials)


def emit_shared_robdd(n_in: int, n_out: int, words: Sequence[int]) -> Tuple[str, int]:
    """Shared ordered decision DAG with canonical complemented edges.

    Edge zero is constant false and ~zero is constant true. Every other
    nonnegative edge names a scalar node; a negative edge complements ~edge.
    Canonical cofactors have zero at their first (all-remaining-inputs-zero)
    entry, so opposite truth functions share the same node graph.
    """
    _validate_table(n_in, n_out, words)
    nodes: List[Tuple[int, int, int]] = []
    unique: dict[Tuple[int, int, int], int] = {}

    @lru_cache(maxsize=None)
    def build(values: bytes, variable: int) -> int:
        first = values[0]
        if values.count(first) == len(values):
            return -1 if first else 0
        if variable >= n_in:
            raise RuntimeError("nonconstant leaf after all input variables")
        if first:
            return ~build(bytes(value ^ 1 for value in values), variable)
        low = build(values[0::2], variable + 1)
        high = build(values[1::2], variable + 1)
        if low == high:
            return low
        key = (variable, low, high)
        if key not in unique:
            unique[key] = len(nodes) + 1
            nodes.append(key)
        return unique[key]

    roots = [build(bytes(table), 0) for table in _bit_tables(words, n_out)]

    def ref(edge: int) -> str:
        if edge == 0:
            return "1'b0"
        if edge == -1:
            return "1'b1"
        return f"n{edge}" if edge > 0 else f"~n{~edge}"

    lines = [
        "// Exact shared Boolean decision DAG with complemented edges.",
        "// This low-level Boolean representation is not classified as high-level RTL.",
        f"module top(input [{n_in - 1}:0] x, output [{n_out - 1}:0] y);",
    ]
    lines.extend(_scalar_declarations("n", range(1, len(nodes) + 1)))
    for node, (variable, low, high) in enumerate(nodes, start=1):
        lines.append(f"  assign n{node} = x[{variable}] ? {ref(high)} : {ref(low)};")
    for output, root in enumerate(roots):
        lines.append(f"  assign y[{output}] = {ref(root)};")
    lines.extend(("endmodule", ""))
    return "\n".join(lines), len(nodes)


def choose_exact_boolean_fallback(
    n_in: int, n_out: int, words: Sequence[int]
) -> Tuple[str, str, int]:
    """Keep the exact fallback while sharing repeated source operations.

    Candidate selection uses the unchanged package syntax-cost calculator;
    every candidate is generated from the supplied complete truth function.
    The optimized representations remain low-level Boolean recoveries.
    """
    from .boolean_compact import choose_compact_boolean
    return choose_compact_boolean(n_in, n_out, words)

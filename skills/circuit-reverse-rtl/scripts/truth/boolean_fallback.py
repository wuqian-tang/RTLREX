"""Exact structural Boolean fallbacks for complete truth tables.

These emitters preserve all table entries but do not claim word-level recovery.
They are deliberately opt-in so a successful low-level fallback cannot be
confused with a recovered high-level RTL result.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Sequence, Tuple


def _bit_tables(words: Sequence[int], n_out: int) -> List[bytearray]:
    return [bytearray((word >> bit) & 1 for word in words) for bit in range(n_out)]


def emit_shared_anf(n_in: int, n_out: int, words: Sequence[int]) -> Tuple[str, int]:
    """Return Verilog and the number of shared algebraic-normal-form monomials."""

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
        lines.append(f"  wire [{len(monomials) - 1}:0] m;")
    for term in monomials:
        rhs = "1'b1" if term == 0 else " & ".join(
            f"x[{bit}]" for bit in range(n_in) if term & (1 << bit)
        )
        lines.append(f"  assign m[{index[term]}] = {rhs};")
    for output, terms in enumerate(functions):
        rhs = " ^ ".join(f"m[{index[term]}]" for term in terms) or "1'b0"
        lines.append(f"  assign y[{output}] = {rhs};")
    lines.extend(("endmodule", ""))
    return "\n".join(lines), len(monomials)


def emit_shared_robdd(n_in: int, n_out: int, words: Sequence[int]) -> Tuple[str, int]:
    """Return Verilog and the number of nodes in one shared ordered BDD."""

    nodes: List[Tuple[int, int, int]] = []
    unique: dict[Tuple[int, int, int], int] = {}

    @lru_cache(maxsize=None)
    def build(values: bytes, variable: int) -> int:
        first = values[0]
        if values.count(first) == len(values):
            return 1 if first else 0
        if variable >= n_in:
            raise RuntimeError("nonconstant leaf after all input variables")
        low = build(values[0::2], variable + 1)
        high = build(values[1::2], variable + 1)
        if low == high:
            return low
        key = (variable, low, high)
        if key in unique:
            return unique[key]
        node = len(nodes) + 2
        unique[key] = node
        nodes.append(key)
        return node

    roots = [build(bytes(table), 0) for table in _bit_tables(words, n_out)]

    def ref(node: int) -> str:
        if node == 0:
            return "1'b0"
        if node == 1:
            return "1'b1"
        return f"n[{node}]"

    lines = [
        "// Exact truth-derived shared ROBDD fallback.",
        "// This low-level Boolean representation is not classified as high-level RTL.",
        f"module top(input [{n_in - 1}:0] x, output [{n_out - 1}:0] y);",
    ]
    if nodes:
        lines.append(f"  wire [{len(nodes) + 1}:2] n;")
    for node, (variable, low, high) in enumerate(nodes, start=2):
        lines.append(f"  assign n[{node}] = x[{variable}] ? {ref(high)} : {ref(low)};")
    for output, root in enumerate(roots):
        lines.append(f"  assign y[{output}] = {ref(root)};")
    lines.extend(("endmodule", ""))
    return "\n".join(lines), len(nodes)


def choose_exact_boolean_fallback(
    n_in: int, n_out: int, words: Sequence[int]
) -> Tuple[str, str, int]:
    """Generate ANF and ROBDD forms and choose the smaller Verilog artifact."""

    anf, anf_nodes = emit_shared_anf(n_in, n_out, words)
    robdd, robdd_nodes = emit_shared_robdd(n_in, n_out, words)
    if len(anf) <= len(robdd):
        return "structural ANF fallback", anf, anf_nodes
    return "shared ROBDD fallback", robdd, robdd_nodes

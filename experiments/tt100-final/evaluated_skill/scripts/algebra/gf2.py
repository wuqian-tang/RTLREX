#!/usr/bin/env python3
"""GF(2) linear algebra and ANF fitting helpers.

Rows are represented as Python integers. Bit i is coefficient i. This keeps
Gaussian elimination fast enough for the small and medium Boolean systems used
while reverse-engineering flattened combinational netlists.
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

BitTerm = Tuple[str, ...]


def solve(rows: Sequence[int], rhs: Sequence[int], nvars: int) -> Optional[int]:
    """Return one solution bit-vector for rows*x = rhs over GF(2).

    Free variables are set to zero. Return None if the system is inconsistent.
    """
    augmented = [int(row) | ((int(bit) & 1) << nvars) for row, bit in zip(rows, rhs)]
    rank = 0
    pivots: List[int] = []
    for col in range(nvars):
        pivot = None
        for r in range(rank, len(augmented)):
            if (augmented[r] >> col) & 1:
                pivot = r
                break
        if pivot is None:
            continue
        augmented[rank], augmented[pivot] = augmented[pivot], augmented[rank]
        for r in range(len(augmented)):
            if r != rank and ((augmented[r] >> col) & 1):
                augmented[r] ^= augmented[rank]
        pivots.append(col)
        rank += 1

    coeff_mask = (1 << nvars) - 1
    for row in augmented[rank:]:
        if (row & coeff_mask) == 0 and ((row >> nvars) & 1):
            return None

    solution = 0
    for r, col in enumerate(pivots):
        if (augmented[r] >> nvars) & 1:
            solution |= 1 << col
    return solution


def monomial_terms(bits: Sequence[str], max_degree: int, include_const: bool = True) -> List[BitTerm]:
    terms: List[BitTerm] = [()] if include_const else []
    for degree in range(1, max_degree + 1):
        terms.extend(tuple(combo) for combo in combinations(bits, degree))
    return terms


def bit_value(token: str, values: Mapping[str, int]) -> int:
    if "[" not in token:
        return int(values.get(token, 0)) & 1
    name, bit = token[:-1].split("[", 1)
    return (int(values.get(name, 0)) >> int(bit)) & 1


def term_value(term: BitTerm, values: Mapping[str, int]) -> int:
    value = 1
    for token in term:
        value &= bit_value(token, values)
    return value


def row_for_terms(terms: Sequence[BitTerm], values: Mapping[str, int]) -> int:
    row = 0
    for i, term in enumerate(terms):
        if term_value(term, values):
            row |= 1 << i
    return row


def fit_bits(
    samples: Sequence[Mapping[str, int]],
    outputs: Sequence[int],
    terms: Sequence[BitTerm],
) -> Optional[int]:
    rows = [row_for_terms(terms, sample) for sample in samples]
    return solve(rows, outputs, len(terms))


def term_expression(term: BitTerm) -> str:
    if not term:
        return "1'b1"
    if len(term) == 1:
        return term[0]
    return "(" + " & ".join(term) + ")"


def formula_expression(coeffs: int, terms: Sequence[BitTerm]) -> str:
    pieces = [term_expression(term) for i, term in enumerate(terms) if (coeffs >> i) & 1]
    return " ^ ".join(pieces) if pieces else "1'b0"


def _parse_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise TypeError(f"expected int or int string, got {type(value).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    solve_p = sub.add_parser("solve", help="solve a GF(2) linear system from JSON")
    solve_p.add_argument("--json", required=True, help='JSON object with "rows", "rhs", and "nvars"')

    args = parser.parse_args()
    if args.command == "solve":
        payload = json.loads(args.json)
        rows = [_parse_int(row) for row in payload["rows"]]
        rhs = [_parse_int(bit) & 1 for bit in payload["rhs"]]
        nvars = int(payload["nvars"])
        solution = solve(rows, rhs, nvars)
        print(json.dumps({"solution": solution, "hex": None if solution is None else hex(solution)}))
        return 0 if solution is not None else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


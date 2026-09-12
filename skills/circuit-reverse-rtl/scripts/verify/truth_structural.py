#!/usr/bin/env python3
"""Exhaustively replay structural ANF/ROBDD Verilog over a complete truth table.

The parser accepts only the small continuous-assignment grammar emitted by
``truth.boolean_fallback``.  Each Python integer holds a Boolean signal over
the complete input domain, making the result exact rather than sampled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import resource
import sys
import time
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truth.utils import read_truth_lines


REF = re.compile(r"([A-Za-z_]\w*)\[(\d+)\]")
ASSIGN = re.compile(r"assign\s+([A-Za-z_]\w*)\[(\d+)\]\s*=\s*(.*?);", re.S)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packed_vector(bits: str) -> int:
    packed = bytearray((len(bits) + 7) // 8)
    for index, value in enumerate(bits):
        if value == "1":
            packed[index >> 3] |= 1 << (index & 7)
    return int.from_bytes(packed, "little")


def _input_vector(bit: int, domain: int) -> int:
    packed = bytearray((domain + 7) // 8)
    for index in range(domain):
        if index & (1 << bit):
            packed[index >> 3] |= 1 << (index & 7)
    return int.from_bytes(packed, "little")


def verify(truth: Path, candidate: Path) -> Dict[str, object]:
    started = time.monotonic()
    rows = read_truth_lines(truth)
    domain = len(rows[0])
    n_inputs = domain.bit_length() - 1
    n_outputs = len(rows)
    source = re.sub(r"//.*", "", candidate.read_text())
    assignments = [(name, int(index), expr.strip()) for name, index, expr in ASSIGN.findall(source)]
    input_match = re.search(r"input\s+\[(\d+)\s*:\s*0\]\s+(\w+)", source)
    output_match = re.search(r"output\s+\[(\d+)\s*:\s*0\]\s+(\w+)", source)
    if not assignments or not input_match or not output_match:
        raise ValueError("candidate is outside the supported structural fallback grammar")
    input_name = input_match.group(2)
    output_name = output_match.group(2)
    if int(input_match.group(1)) + 1 != n_inputs or int(output_match.group(1)) + 1 != n_outputs:
        raise ValueError("candidate and truth-table dimensions differ")

    full_mask = (1 << domain) - 1
    signals = {(input_name, bit): _input_vector(bit, domain) for bit in range(n_inputs)}

    def atom(token: str) -> int:
        token = token.strip().strip("()")
        if token == "1'b0":
            return 0
        if token == "1'b1":
            return full_mask
        match = REF.fullmatch(token)
        if not match:
            raise ValueError(f"unsupported atom: {token[:120]}")
        key = (match.group(1), int(match.group(2)))
        if key not in signals:
            raise ValueError(f"forward or missing reference: {key}")
        return signals[key]

    def product(term: str) -> int:
        value = full_mask
        for token in term.split("&"):
            value &= atom(token)
        return value

    node_count = 0
    output_count = 0
    for name, index, expr in assignments:
        ternary = re.fullmatch(r"(\w+\[\d+\])\s*\?\s*(.*?)\s*:\s*(.*)", expr, re.S)
        if ternary:
            select = atom(ternary.group(1))
            high = atom(ternary.group(2))
            low = atom(ternary.group(3))
            value = (select & high) | ((full_mask ^ select) & low)
        elif "^" in expr:
            value = 0
            for token in expr.split("^"):
                value ^= product(token)
        elif "&" in expr:
            value = product(expr)
        else:
            value = atom(expr)
        signals[(name, index)] = value
        if name == output_name:
            output_count += 1
        else:
            node_count += 1

    mismatches = []
    for output, row in enumerate(rows):
        actual = signals.get((output_name, output))
        expected = _packed_vector(row[::-1])
        if actual is None:
            mismatches.append({"output": output, "reason": "missing assignment"})
            continue
        delta = actual ^ expected
        if delta:
            mismatches.append({"output": output, "first_input": (delta & -delta).bit_length() - 1})
    strict = not mismatches and output_count == n_outputs
    return {
        "schema_version": 1,
        "status": "pass" if strict else "fail",
        "strict": strict,
        "method": "complete-domain bit-parallel structural replay",
        "truth": str(truth),
        "truth_sha256": _sha256(truth),
        "candidate": str(candidate),
        "candidate_sha256": _sha256(candidate),
        "n_inputs": n_inputs,
        "n_outputs": n_outputs,
        "vectors_checked": domain,
        "output_bits_checked": output_count,
        "structural_nodes_evaluated": node_count,
        "mismatches": mismatches,
        "runtime_seconds": time.monotonic() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = verify(args.truth, args.candidate)
    except (OSError, ValueError) as exc:
        report = {"status": "error", "strict": False, "error": str(exc)}
    if args.certificate:
        args.certificate.parent.mkdir(parents=True, exist_ok=True)
        args.certificate.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{str(report['status']).upper()} {args.candidate}")
    return 0 if report.get("strict") else 1


if __name__ == "__main__":
    raise SystemExit(main())

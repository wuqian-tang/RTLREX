#!/usr/bin/env python3
"""Recursively remove primitive gates whose outputs are unused."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


GATE_RE = re.compile(r"\s*(and|or|xor|xnor|nand|nor|not|buf)\s+\S+\(([^)]*)\);")
ASSIGN_RE = re.compile(r"\s*assign\s+(.+?)\s*=\s*(.+);")
WIRE_RE = re.compile(r"\b(?:w__\d+|[A-Za-z_][A-Za-z0-9_$]*)\b")


def primitive_output(line: str) -> str | None:
    match = GATE_RE.match(line)
    if not match:
        return None
    args = [arg.strip() for arg in match.group(2).split(",")]
    return args[0] if args else None


def primitive_inputs(line: str) -> list[str]:
    match = GATE_RE.match(line)
    if not match:
        return []
    args = [arg.strip() for arg in match.group(2).split(",")]
    return args[1:]


def prune(lines: list[str], roots: set[str]) -> tuple[list[str], int]:
    removed_total = 0
    while True:
        uses: dict[str, int] = {}
        gate_outputs: dict[str, int] = {}

        for idx, line in enumerate(lines):
            out = primitive_output(line)
            if out:
                gate_outputs[out] = idx
                for name in primitive_inputs(line):
                    uses[name] = uses.get(name, 0) + 1
                continue

            assign = ASSIGN_RE.match(line)
            if assign:
                _lhs, rhs = assign.groups()
                for name in WIRE_RE.findall(rhs):
                    uses[name] = uses.get(name, 0) + 1

        remove = {
            idx for out, idx in gate_outputs.items()
            if uses.get(out, 0) == 0 and out not in roots
        }
        if not remove:
            return lines, removed_total
        removed_total += len(remove)
        lines = [line for idx, line in enumerate(lines) if idx not in remove]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verilog", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--roots", default="out1,out2", help="comma-separated signal roots to preserve")
    args = parser.parse_args()

    if args.in_place and args.output:
        parser.error("--in-place and --output are mutually exclusive")
    roots = {name for name in args.roots.split(",") if name}
    lines, removed = prune(args.verilog.read_text().splitlines(), roots)
    text = "\n".join(lines) + "\n"
    if args.in_place:
        args.verilog.write_text(text)
    elif args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    print(f"removed_gates {removed}", file=__import__("sys").stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

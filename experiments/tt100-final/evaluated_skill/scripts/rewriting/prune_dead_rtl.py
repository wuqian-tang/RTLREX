#!/usr/bin/env python3
"""Remove dead continuous assigns, primitive gates, and wire declarations.

This is intended for post-reversal cleanup after output cones have been
replaced by word-level RTL. It computes a conservative backward reachability
set from output declarations and optional roots, then keeps only assignments
and primitive gates that define reachable signals.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_$]*\b")
OUTPUT_RE = re.compile(r"^\s*output\s+(?:signed|unsigned)?\s*(?:\[[^\]]+\])?\s*([^;]+);", re.S)
WIRE_RE = re.compile(r"^(\s*wire\s+(?:signed|unsigned)?\s*(?:\[[^\]]+\])?\s*)([^;]+)(;\s*)$", re.S)
ASSIGN_RE = re.compile(r"^\s*assign\s+(.+?)\s*=\s*(.+);\s*$", re.S)
GATE_RE = re.compile(r"^\s*(and|or|xor|xnor|nand|nor|not|buf)\s+\S+\((.*?)\);\s*$", re.S)
KEYWORDS = {
    "assign", "wire", "signed", "unsigned", "module", "endmodule", "input", "output",
    "and", "or", "xor", "xnor", "nand", "nor", "not", "buf",
}


@dataclass
class Statement:
    text: str
    kind: str
    defines: set[str]
    uses: set[str]


def split_statements(text: str) -> list[str]:
    statements: list[str] = []
    cur: list[str] = []
    for line in text.splitlines(keepends=True):
        if not cur and line.strip() == "endmodule":
            statements.append(line)
            continue
        cur.append(line)
        if ";" in line:
            statements.append("".join(cur))
            cur = []
    if cur:
        statements.append("".join(cur))
    return statements


def strip_select(name: str) -> str:
    return name.split("[", 1)[0].strip()


def split_names(text: str) -> list[str]:
    names: list[str] = []
    for part in text.split(","):
        name = strip_select(part)
        if name:
            names.append(name)
    return names


def identifiers(text: str) -> set[str]:
    names: set[str] = set()
    for match in IDENT_RE.finditer(text):
        if match.start() > 0 and text[match.start() - 1] == "'":
            continue
        name = match.group(0)
        if name not in KEYWORDS:
            names.add(name)
    return names


def lhs_identifiers(text: str) -> set[str]:
    return {strip_select(name) for name in identifiers(text)}


def primitive_args(arg_text: str) -> list[str]:
    return [arg.strip() for arg in arg_text.split(",") if arg.strip()]


def parse_statement(text: str) -> Statement:
    assign = ASSIGN_RE.match(text)
    if assign:
        lhs, rhs = assign.groups()
        return Statement(text, "assign", lhs_identifiers(lhs), identifiers(rhs))

    gate = GATE_RE.match(text)
    if gate:
        args = primitive_args(gate.group(2))
        if not args:
            return Statement(text, "other", set(), set())
        return Statement(text, "gate", {strip_select(args[0])}, identifiers(",".join(args[1:])))

    return Statement(text, "other", set(), identifiers(text))


def output_roots(statements: list[str]) -> set[str]:
    roots: set[str] = set()
    for stmt in statements:
        match = OUTPUT_RE.match(stmt)
        if match:
            roots.update(split_names(match.group(1)))
    return roots


def reachable_statement_indexes(statements: list[Statement], roots: set[str]) -> tuple[set[int], set[str]]:
    keep: set[int] = set()
    required = set(roots)
    changed = True
    while changed:
        changed = False
        for idx in range(len(statements) - 1, -1, -1):
            stmt = statements[idx]
            if stmt.kind not in {"assign", "gate"} or idx in keep:
                continue
            if stmt.defines & required:
                keep.add(idx)
                before = len(required)
                required.update(stmt.uses)
                if len(required) != before:
                    changed = True
    return keep, required


def filter_wire_decl(text: str, required: set[str]) -> tuple[str | None, int]:
    match = WIRE_RE.match(text)
    if not match:
        return text, 0
    prefix, names_text, suffix = match.groups()
    names = [name.strip() for name in names_text.split(",") if name.strip()]
    kept = [name for name in names if strip_select(name) in required]
    removed = len(names) - len(kept)
    if not kept:
        return None, removed
    return prefix + ", ".join(kept) + suffix, removed


def prune(text: str, roots: set[str]) -> tuple[str, dict[str, int]]:
    raw = split_statements(text)
    roots = set(roots) | output_roots(raw)
    parsed = [parse_statement(stmt) for stmt in raw]
    keep_reachable, required = reachable_statement_indexes(parsed, roots)

    out: list[str] = []
    removed_assigns = 0
    removed_gates = 0
    removed_wires = 0
    for idx, stmt in enumerate(parsed):
        if stmt.kind == "assign" and idx not in keep_reachable:
            removed_assigns += 1
            continue
        if stmt.kind == "gate" and idx not in keep_reachable:
            removed_gates += 1
            continue
        filtered, removed = filter_wire_decl(stmt.text, required | roots)
        removed_wires += removed
        if filtered is not None:
            out.append(filtered)

    return "".join(out), {
        "removed_assigns": removed_assigns,
        "removed_gates": removed_gates,
        "removed_wire_names": removed_wires,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verilog", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--roots", default="", help="comma-separated additional roots to preserve")
    args = parser.parse_args()

    if args.in_place and args.output:
        parser.error("--in-place and --output are mutually exclusive")

    roots = {name for name in args.roots.split(",") if name}
    text, stats = prune(args.verilog.read_text(), roots)
    if args.in_place:
        args.verilog.write_text(text)
    elif args.output:
        args.output.write_text(text)
    else:
        print(text, end="")

    print(" ".join(f"{key} {value}" for key, value in stats.items()), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

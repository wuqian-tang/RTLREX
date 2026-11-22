#!/usr/bin/env python3
"""Report primary-input cones for primitive-gate Verilog signals."""

from __future__ import annotations

import argparse
import json
import re
from functools import lru_cache
from pathlib import Path


GATE_RE = re.compile(r"^\s*(and|or|xor|xnor|nand|nor|not|buf)\s+\S+\(([^)]*)\);")
ASSIGN_RE = re.compile(r"^\s*assign\s+(.+?)\s*=\s*(.+);")
TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_$]*\b")


def base_name(name: str) -> str:
    return name.split("[", 1)[0].strip()


def parse_inputs(text: str) -> set[str]:
    inputs: set[str] = set()
    for match in re.finditer(r"^\s*input\s+(?:\[[^\]]+\]\s*)?([^;]+);", text, re.M):
        for raw in match.group(1).split(","):
            name = raw.strip().split()[-1]
            if name:
                inputs.add(base_name(name))
    return inputs


def parse_dependencies(text: str) -> dict[str, set[str]]:
    deps: dict[str, set[str]] = {}
    for line in text.splitlines():
        gate = GATE_RE.match(line)
        if gate:
            args = [arg.strip() for arg in gate.group(2).split(",")]
            if args:
                deps[base_name(args[0])] = {base_name(arg) for arg in args[1:]}
            continue

        assign = ASSIGN_RE.match(line)
        if not assign:
            continue
        lhs, rhs = assign.groups()
        rhs_deps = {base_name(tok) for tok in TOKEN_RE.findall(rhs)}
        if lhs.strip().startswith("{"):
            for name in TOKEN_RE.findall(lhs):
                deps[base_name(name)] = rhs_deps
        else:
            names = TOKEN_RE.findall(lhs)
            if names:
                deps[base_name(names[0])] = rhs_deps
    return deps


def cone_for(signal: str, inputs: set[str], deps: dict[str, set[str]]) -> set[str]:
    @lru_cache(None)
    def visit(name: str) -> frozenset[str]:
        name = base_name(name)
        if name in inputs:
            return frozenset({name})
        result: set[str] = set()
        for dep in deps.get(name, set()):
            result.update(visit(dep))
        return frozenset(result)

    return set(visit(signal))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--signals", action="append", required=True, help="signal name; repeatable")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    text = args.netlist.read_text()
    inputs = parse_inputs(text)
    deps = parse_dependencies(text)
    result = {sig: sorted(cone_for(sig, inputs, deps), key=lambda n: (len(n), n)) for sig in args.signals}

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for sig, cone in result.items():
            print(f"{sig}: {' '.join(cone)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

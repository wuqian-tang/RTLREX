#!/usr/bin/env python3
"""Match a sampled Python word expression to internal one-bit wires."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
import sys
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sampling.fast_sampler import random_vectors, sample_many


def sx(value: int, width: int, out_width: int | None = None) -> int:
    value &= (1 << width) - 1
    out_width = width if out_width is None else out_width
    if value & (1 << (width - 1)):
        value |= ((1 << max(out_width - width, 0)) - 1) << width
    return value & ((1 << out_width) - 1)


def parse_fix(items: list[str]) -> dict[str, int]:
    fixes: dict[str, int] = {}
    for item in items:
        name, value = item.split("=", 1)
        fixes[name] = int(value, 0)
    return fixes


def eval_expr(expr: str, vector: dict[str, int], mask: int, width: int) -> int:
    locals_dict: dict[str, Any] = dict(vector)
    locals_dict.update({"mask": mask, "width": width, "sx": sx})
    return int(eval(expr, {"__builtins__": {}}, locals_dict)) & mask


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--expr", required=True, help="Python expression using input names, mask, width, sx()")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--count", type=int, default=512)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--fix", action="append", default=[], help="force input value, e.g. in3=0")
    parser.add_argument("--prefix", default="w__", help="only report matching signals with this prefix; empty reports all")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    vectors = random_vectors(args.netlist, args.count, seed=args.seed)
    fixes = parse_fix(args.fix)
    for vec in vectors:
        vec.update(fixes)

    rows = sample_many(args.netlist, vectors, all_signals=True)
    pattern_to_names: dict[tuple[int, ...], list[str]] = defaultdict(list)
    for name in rows[0]:
        if args.prefix and not name.startswith(args.prefix):
            continue
        pattern_to_names[tuple(row[name] & 1 for row in rows)].append(name)

    mask = (1 << args.width) - 1
    values = [eval_expr(args.expr, vec, mask, args.width) for vec in vectors]
    result: list[dict[str, object]] = []
    for bit in range(args.width):
        pattern = tuple((value >> bit) & 1 for value in values)
        result.append({"bit": bit, "matches": sorted(pattern_to_names.get(pattern, []))})

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result:
            matches = " ".join(item["matches"])
            print(f"bit {item['bit']}: {matches}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

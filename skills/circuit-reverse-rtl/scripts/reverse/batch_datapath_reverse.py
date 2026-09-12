#!/usr/bin/env python3
"""Run the datapath reverser over a directory of primitive netlists."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reverse.datapath_reverse import ROOT, generate_one, resolve_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench-dir", required=True, help="directory containing case subdirectories")
    parser.add_argument("--out-dir", default="output", help="directory for reversed Verilog files")
    parser.add_argument("--sim-vectors", type=int, default=64, help="random iverilog vectors per compact candidate")
    parser.add_argument("--no-iverilog", action="store_true", help="disable iverilog candidate validation")
    args = parser.parse_args(argv)

    bench_dir = resolve_path(args.bench_dir)
    out_dir = resolve_path(args.out_dir)
    paths = sorted(bench_dir.glob("*/top_primitive.v"))
    if not paths:
        raise SystemExit(f"no top_primitive.v files found under {bench_dir}")

    for path in paths:
        method = generate_one(path, out_dir, sim_vectors=args.sim_vectors, use_iverilog=not args.no_iverilog)
        rel = path.parent.relative_to(bench_dir) if path.parent.is_relative_to(bench_dir) else Path(path.parent.name)
        print(f"{rel}: {method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

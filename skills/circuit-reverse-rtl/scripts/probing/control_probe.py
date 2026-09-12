#!/usr/bin/env python3
"""Probe all-zero and one-hot single-bit controls for selected outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reverse.datapath_reverse import parse_spec
from sampling.fast_sampler import random_vectors, sample_many


def parse_outputs(text: str) -> dict[str, int]:
    outputs: dict[str, int] = {}
    for item in text.split(","):
        name, width = item.split(":", 1)
        outputs[name] = int(width, 0)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--outputs", required=True, help="comma list like out1:13,out2:13")
    parser.add_argument("--controls", default="", help="comma list; default all 1-bit inputs")
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    spec = parse_spec(args.netlist)
    outputs = parse_outputs(args.outputs)
    controls = [c for c in args.controls.split(",") if c] or [
        name for name, width in spec.inputs.items() if width == 1
    ]
    vectors: list[dict[str, int]] = []
    meta: list[tuple[int, str]] = []

    bases = random_vectors(args.netlist, args.samples, seed=args.seed)
    for sample_idx, base in enumerate(bases):
        for ctrl in controls:
            base[ctrl] = 0
        vectors.append(dict(base))
        meta.append((sample_idx, "base"))
        for ctrl in controls:
            vec = dict(base)
            vec[ctrl] = 1
            vectors.append(vec)
            meta.append((sample_idx, ctrl))

    rows = sample_many(args.netlist, vectors, signals=outputs)
    base_rows: dict[int, dict[str, int]] = {}
    for (sample_idx, ctrl), row in zip(meta, rows):
        if ctrl == "base":
            base_rows[sample_idx] = row

    for (sample_idx, ctrl), row in zip(meta, rows):
        base = base_rows[sample_idx]
        deltas = {
            name: (row[name] - base[name]) & ((1 << width) - 1)
            for name, width in outputs.items()
        }
        print(json.dumps({
            "sample": sample_idx,
            "control": ctrl,
            "outputs": {name: row[name] for name in outputs},
            "deltas": deltas,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

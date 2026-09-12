#!/usr/bin/env python3
"""Describe high-level behavior of .truth files without using benchmark names."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from truth.describe import describe_truth
from truth.utils import read_truth_words


def collect_truths(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob("*.truth"))
    return [path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help=".truth file or directory")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = []
    for truth in collect_truths(Path(args.input)):
        n_in, n_out, words = read_truth_words(truth)
        desc = describe_truth(n_in, n_out, words)
        row = {
            "case": truth.stem,
            "truth": str(truth),
            "n_inputs": n_in,
            "n_outputs": n_out,
            "status": "described" if desc else "unknown",
        }
        if desc:
            row.update({"family": desc.family, "detail": desc.detail, "confidence": desc.confidence})
        rows.append(row)
    if args.json:
        print(json.dumps(rows if len(rows) != 1 else rows[0], indent=2, sort_keys=True))
    else:
        for row in rows:
            if row["status"] == "described":
                print(f"{row['case']}: {row['family']} - {row['detail']}")
            else:
                print(f"{row['case']}: unknown ({row['n_inputs']}->{row['n_outputs']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

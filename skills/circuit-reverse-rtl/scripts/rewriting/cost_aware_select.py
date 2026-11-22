#!/usr/bin/env python3
"""Select the lower-cost implementation after reverse generation.

This is intentionally a rewriting/post-processing step. The datapath reverser
should emit its best behavioral RTL candidate first; this module can then pick
between that candidate and a fallback primitive netlist using the active cost
CSV.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cost.RTL_cost_calculator import evaluate_rtl, set_operator_cost_csv


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def rtl_cost(path: Path, cost_csv: Optional[Path]) -> int:
    if cost_csv is not None:
        set_operator_cost_csv(str(cost_csv))
    cost, _module_costs, _detail = evaluate_rtl(str(path))
    return cost


def primitive_for_candidate(candidate: Path, input_dir: Path) -> Path:
    return input_dir / candidate.stem / "top_primitive.v"


def select_one(candidate: Path, primitive: Path, output: Path, cost_csv: Optional[Path]) -> dict[str, object]:
    candidate_cost = rtl_cost(candidate, cost_csv)
    primitive_cost = rtl_cost(primitive, cost_csv)
    use_candidate = candidate_cost <= primitive_cost
    source = candidate if use_candidate else primitive
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    return {
        "case": candidate.stem,
        "candidate": str(candidate),
        "primitive": str(primitive),
        "output": str(output),
        "candidate_cost": candidate_cost,
        "primitive_cost": primitive_cost,
        "selected": "candidate" if use_candidate else "primitive",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", required=True, help="directory containing generated testXX.v candidates")
    parser.add_argument("--input-dir", required=True, help="benchmark directory containing testXX/top_primitive.v")
    parser.add_argument("--out-dir", required=True, help="directory for selected lower-cost RTL files")
    parser.add_argument("--cost-csv", help="cost CSV to use")
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    args = parser.parse_args(argv)

    candidate_dir = resolve_path(args.candidate_dir)
    input_dir = resolve_path(args.input_dir)
    out_dir = resolve_path(args.out_dir)
    cost_csv = resolve_path(args.cost_csv) if args.cost_csv else None

    rows = []
    for candidate in sorted(candidate_dir.glob("*.v")):
        primitive = primitive_for_candidate(candidate, input_dir)
        if not primitive.exists():
            raise SystemExit(f"missing primitive for {candidate}: {primitive}")
        rows.append(select_one(candidate, primitive, out_dir / candidate.name, cost_csv))

    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row['case']}: selected={row['selected']} "
                f"candidate_cost={row['candidate_cost']} primitive_cost={row['primitive_cost']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify benchmark identities against the saved final experiment inputs."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Input checksum mismatch: {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pa30-dir", type=Path,
                        help="Also check separately obtained PA-30 original inputs")
    args = parser.parse_args()
    dataset = ROOT / "benchmarks/tt100"
    source = json.loads((dataset / "source.json").read_text())
    final = json.loads((ROOT / "experiments/tt100-final/input_manifest.json").read_text())
    expected = {row["case"]: row for row in final}
    cases = {f"ex{i}" for i in range(200, 300)}
    if len(final) != 100 or set(expected) != cases:
        raise ValueError("Final TT-100 input manifest is incomplete")
    if len(source["inputs"]) != 100 or {row["case"] for row in source["inputs"]} != cases:
        raise ValueError("TT-100 source manifest is incomplete")
    if {p.stem for p in (dataset / "truth").glob("*.truth")} != cases:
        raise ValueError("Included TT-100 inputs do not match the expected cases")
    check(dataset / source["license_file"], source["license_sha256"])
    for row in source["inputs"]:
        original = expected[row["case"]]
        if any(row[key] != original[key] for key in
               ("sha256", "n_inputs", "n_outputs")):
            raise ValueError("Source and final input manifests disagree: " + row["case"])
        if row["path"] != f"truth/{row['case']}.truth":
            raise ValueError("Unexpected TT-100 source path")
        check(dataset / row["path"], original["sha256"])
    count_pa = 0
    if args.pa30_dir is not None:
        final_pa = json.loads((ROOT / "experiments/pa30-arithmetic/input_manifest.json").read_text())
        rows = final_pa["cases"]
        if len(rows) != 30 or {r["case"] for r in rows} != {f"test{i:02d}" for i in range(1, 31)}:
            raise ValueError("Final PA-30 input manifest is incomplete")
        for row in rows:
            check(args.pa30_dir / row["original_gate_input"], row["original_gate_sha256"])
        count_pa = len(rows)
    print(json.dumps({"status": "pass", "TT100_inputs": 100,
                      "PA30_inputs_checked": count_pa}))


if __name__ == "__main__":
    main()

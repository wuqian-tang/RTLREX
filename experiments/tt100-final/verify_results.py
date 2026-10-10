#!/usr/bin/env python3
"""Recompute published TT-100 aggregates without EDA tools or an LLM."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARMS = ("with_skill", "no_skill")


def flag(value: str) -> bool:
    if value not in ("True", "False"):
        raise ValueError(f"Invalid Boolean: {value!r}")
    return value == "True"


def load_rows() -> list[dict]:
    with (ROOT / "case_results.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("V", "H", "generation_timeout", "usage_available"):
            row[key] = flag(row[key])
        row["policy_compliant"] = flag(row["policy_compliant"]) if row["policy_compliant"] else None
        for key in ("syntax_cost", "input_tokens", "cached_input_tokens", "output_tokens"):
            row[key] = int(row[key]) if row[key] else None
        row["generation_seconds"] = float(row["generation_seconds"])
        assert row["arm"] in ARMS
        assert not row["H"] or row["V"]
        assert math.isfinite(row["generation_seconds"]) and row["generation_seconds"] >= 0
        assert not row["V"] or row["syntax_cost"] is not None
        assert not row["H"] or row["policy_compliant"]
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            assert row["usage_available"] == (row[key] is not None)
    assert len(rows) == 200
    assert len({(r["case"], r["arm"]) for r in rows}) == 200
    expected = {f"ex{i}" for i in range(200, 300)}
    for arm in ARMS:
        assert {r["case"] for r in rows if r["arm"] == arm} == expected
    return rows


def compute(rows: list[dict]) -> dict:
    conditions = {}
    for arm in ARMS:
        arm_rows = [r for r in rows if r["arm"] == arm]
        usage = [r for r in arm_rows if r["usage_available"]]
        conditions[arm] = {
            "cases": len(arm_rows),
            "V": sum(r["V"] for r in arm_rows),
            "H": sum(r["H"] for r in arm_rows),
            "generation_wall_seconds_sum": sum(r["generation_seconds"] for r in arm_rows),
            "generation_timeouts": sum(r["generation_timeout"] for r in arm_rows),
            "recorded_usage_trials": len(usage),
            "missing_usage_trials": len(arm_rows) - len(usage),
            "recorded_usage_sum": {
                k: sum(r[k] for r in usage)
                for k in ("input_tokens", "cached_input_tokens", "output_tokens")
            },
        }
    indexed = {(r["case"], r["arm"]): r for r in rows}
    comparisons = {}
    for endpoint in ("V", "H"):
        pairs = []
        for case in sorted({r["case"] for r in rows}):
            with_skill, no_skill = (indexed[(case, arm)] for arm in ARMS)
            assert with_skill["input_sha256"] == no_skill["input_sha256"]
            if with_skill[endpoint] and no_skill[endpoint]:
                pairs.append((with_skill, no_skill))
        means = {
            arm: sum(pair[i]["syntax_cost"] for pair in pairs) / len(pairs)
            for i, arm in enumerate(ARMS)
        }
        comparisons[endpoint] = {
            "paired_cases": len(pairs),
            "case_ids": [pair[0]["case"] for pair in pairs],
            "with_skill_wins": sum(a["syntax_cost"] < b["syntax_cost"] for a, b in pairs),
            "ties": sum(a["syntax_cost"] == b["syntax_cost"] for a, b in pairs),
            "no_skill_wins": sum(a["syntax_cost"] > b["syntax_cost"] for a, b in pairs),
            "with_skill_cost_mean": means["with_skill"],
            "no_skill_cost_mean": means["no_skill"],
            "mean_cost_reduction_percent": 100 * (1 - means["with_skill"] / means["no_skill"]),
            "generation_wall_seconds_sum": {
                arm: sum(pair[i]["generation_seconds"] for pair in pairs)
                for i, arm in enumerate(ARMS)
            },
        }
    return {"schema": "creas-tt100-published-results/v1", "conditions": conditions,
            "paired_cost_runtime": comparisons}


def equivalent(actual, expected) -> bool:
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(equivalent(v, expected[k]) for k, v in actual.items())
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(equivalent(a, b) for a, b in zip(actual, expected))
    if isinstance(actual, float):
        return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8)
    return actual == expected


def verify_function_inventory(indexed: dict, inputs: dict) -> None:
    """Check record correspondence, not the semantics of descriptive labels."""
    with (ROOT / "recovered_functions.csv").open(newline="") as handle:
        inventory = list(csv.DictReader(handle))
    assert len(inventory) == 100
    assert len({r["case"] for r in inventory}) == 100
    assert {r["case"] for r in inventory} == set(inputs)
    groups = {}
    for row in inventory:
        selected = indexed[(row["case"], "with_skill")]
        original = inputs[row["case"]]
        assert row["V"] == "1" and selected["V"]
        assert row["H"] in ("0", "1")
        assert int(row["H"]) == int(selected["H"])
        assert int(row["syntax_cost"]) == selected["syntax_cost"]
        assert int(row["input_bits"]) == original["n_inputs"]
        assert int(row["output_bits"]) == original["n_outputs"]
        assert row["input_sha256"] == selected["input_sha256"] == original["sha256"]
        assert row["candidate_sha256"] == selected["candidate_sha256"]
        assert all(row[k].strip() for k in
                   ("recovered_function_en", "recovered_function_zh", "recovery_description"))
        assert (row["function_group"] == "bit-level Boolean") == (row["H"] == "0")
        groups[row["function_group"]] = groups.get(row["function_group"], 0) + 1
    assert sum(int(r["H"]) for r in inventory) == 80
    assert groups == {"floating-point": 52, "integer": 25, "fixed-point": 3,
                      "bit-level Boolean": 20}


def main() -> None:
    manifest = json.loads((ROOT / "SHA256.json").read_text())
    for name, expected in manifest.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    rows = load_rows()
    actual = compute(rows)
    expected = json.loads((ROOT / "summary.json").read_text())
    assert equivalent(actual, expected), "Published summary does not match per-case records"
    source_inputs = {r["case"]: r["sha256"] for r in json.loads((ROOT / "input_manifest.json").read_text())}
    assert all(r["input_sha256"] == source_inputs[r["case"]] for r in rows)
    indexed = {(r["case"], r["arm"]): r for r in rows}
    source_interfaces = {r["case"]: r for r in json.loads((ROOT / "input_manifest.json").read_text())}
    verify_function_inventory(indexed, source_interfaces)
    with (ROOT / "cost_pairs.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert {r["case"] for r in pairs} == set(actual["paired_cost_runtime"]["V"]["case_ids"])
    assert len(pairs) == 81
    for pair in pairs:
        a, b = (indexed[(pair["case"], arm)] for arm in ARMS)
        assert int(pair["with_skill_Q"]) == a["syntax_cost"]
        assert int(pair["no_skill_Q"]) == b["syntax_cost"]
        assert flag(pair["both_H"]) == (a["H"] and b["H"])
        assert pair["comparison"] == ("Win" if a["syntax_cost"] < b["syntax_cost"] else
                                      "Tie" if a["syntax_cost"] == b["syntax_cost"] else "Loss")
    assert [(actual["conditions"][a]["V"], actual["conditions"][a]["H"]) for a in ARMS] == [(100, 80), (81, 74)]
    for endpoint, counts in (("V", (81, 66, 14, 1)), ("H", (74, 60, 14, 0))):
        comparison = actual["paired_cost_runtime"][endpoint]
        assert tuple(comparison[k] for k in ("paired_cases", "with_skill_wins", "ties", "no_skill_wins")) == counts
    for case in ("ex223", "ex227", "ex228"):
        row = indexed[(case, "no_skill")]
        assert row["V"] and not row["H"] and not row["policy_compliant"]
    print(json.dumps({"status": "pass", "rows": len(rows), "conditions": actual["conditions"],
                      "paired_cases": {k: v["paired_cases"] for k, v in actual["paired_cost_runtime"].items()}}, indent=2))


if __name__ == "__main__":
    main()

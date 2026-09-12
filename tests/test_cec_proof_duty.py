#!/usr/bin/env python3
"""Adversarial unit tests for the serialized SMT2 proof-duty audit."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "skills" / "circuit-reverse-rtl" / "scripts" / "verify" / "cec.py"


def load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("proof_duty_unit_checker", CHECKER)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Cannot import checker: {CHECKER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def balanced_definition(text: str, prefix: str) -> str:
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        block: list[str] = []
        depth = 0
        for part in lines[start:]:
            block.append(part)
            code = part.split(";", 1)[0]
            depth += code.count("(") - code.count(")")
            if depth == 0:
                return "\n".join(block)
    raise AssertionError(f"Missing balanced definition: {prefix}")


def main() -> int:
    checker = load_checker()

    # A timeout/abnormal exit must dominate partial success text already
    # written by a killed solver process.
    abc_timeout = checker.parse_abc_equivalence(
        "Networks are equivalent.\nTimeout after 1s", 124
    )
    if abc_timeout[0] != "timeout" or abc_timeout[1] is not None:
        raise AssertionError(f"ABC partial success survived timeout: {abc_timeout}")
    smt_timeout = checker.parse_smtbmc_equivalence(
        "Status: PASSED\nTimeout after 1s", 124
    )
    if smt_timeout[0] != "timeout" or smt_timeout[1] is not None:
        raise AssertionError(f"SMT partial success survived timeout: {smt_timeout}")
    abc_cancelled = checker.parse_abc_equivalence("Networks are equivalent.", 130)
    if abc_cancelled[0] != "error" or abc_cancelled[1] is not None:
        raise AssertionError(f"ABC partial success survived cancellation: {abc_cancelled}")

    pass_result = checker.CecResult(
        "unit", "ref.v", "impl.v", "cec", "", "pass", True,
        "Networks are equivalent.", "",
    )
    fail_result = checker.CecResult(
        "unit", "ref.v", "impl.v", "&cec", "", "fail", False,
        "Networks are NOT EQUIVALENT.", "",
    )
    unknown_result = checker.CecResult(
        "unit", "ref.v", "impl.v", "dcec", "", "unknown", None,
        "Networks are undecided.", "",
    )
    conflict_result = checker.combine_auto_results(
        "unit", Path("ref.v"), Path("impl.v"), "", [pass_result, fail_result, unknown_result]
    )
    if conflict_result.status != "conflict" or conflict_result.equivalent is not None:
        raise AssertionError(f"ABC conclusive conflict was accepted: {conflict_result}")
    pass_with_unknown = checker.combine_auto_results(
        "unit", Path("ref.v"), Path("impl.v"), "", [pass_result, unknown_result]
    )
    if pass_with_unknown.status != "pass" or pass_with_unknown.equivalent is not True:
        raise AssertionError(f"ABC pass plus unknown was rejected: {pass_with_unknown}")

    # The source-level interface contract includes order, direction, packed
    # range orientation, and signedness before either ABC or SMT lowering.
    with tempfile.TemporaryDirectory(prefix="cec_contract_unit_") as tmp_name:
        tmp = Path(tmp_name)
        reference_contract = tmp / "reference.v"
        identical_contract = tmp / "identical.v"
        signed_mutant = tmp / "signed_mutant.v"
        orientation_mutant = tmp / "orientation_mutant.v"
        reordered_mutant = tmp / "reordered_mutant.v"
        reference_text = """module top(
  input signed [3:0] a,
  input [1:0] b,
  output [0:7] y
);
assign y = a + b;
endmodule
"""
        reference_contract.write_text(reference_text, encoding="utf-8")
        identical_contract.write_text(reference_text, encoding="utf-8")
        # A contradictory ABC outcome cannot be erased by a later solver pass.
        with patch.object(checker, "lower_with_yosys", return_value=checker.ToolResult([], 0, "", "")), \
             patch.object(checker, "audit_aiger_pair", return_value=None), \
             patch.object(checker, "run_auto_abc_attempts", return_value=conflict_result), \
             patch.object(checker, "run_smt_cec_pair", side_effect=AssertionError("conflict reached SMT")), \
             patch.object(checker, "run_algebraic_cec_pair", side_effect=AssertionError("conflict reached algebraic")):
            for strict in (False, True):
                combined = checker.run_cec_pair(
                    "unit", reference_contract, identical_contract, Path("yosys"), Path("abc"),
                    Path("smtbmc"), "auto", "", "z3", 1, True, "aiger", 1, 1,
                    None, False, strict, 1, 1, 1, 1, algebraic_fallback=True,
                )
                if combined.status != "conflict" or combined.equivalent is not None:
                    raise AssertionError("fallback erased a conclusive engine conflict")
        signed_mutant.write_text(
            reference_text.replace("input signed [3:0] a", "input [3:0] a"),
            encoding="utf-8",
        )
        orientation_mutant.write_text(
            reference_text.replace("output [0:7] y", "output [7:0] y"),
            encoding="utf-8",
        )
        reordered_mutant.write_text(
            reference_text.replace(
                "input signed [3:0] a,\n  input [1:0] b",
                "input [1:0] b,\n  input signed [3:0] a",
            ),
            encoding="utf-8",
        )
        same_ok, same_detail = checker.compare_top_port_contracts(
            reference_contract, identical_contract
        )
        if not same_ok or same_detail:
            raise AssertionError(f"Identical interface rejected: {same_detail}")
        interface_negative_details: dict[str, str] = {}
        for label, mutant in {
            "signedness": signed_mutant,
            "orientation": orientation_mutant,
            "order": reordered_mutant,
        }.items():
            mutant_ok, mutant_detail = checker.compare_top_port_contracts(
                reference_contract, mutant
            )
            if mutant_ok or "do not match" not in mutant_detail:
                raise AssertionError(
                    f"Interface {label} mismatch accepted: {mutant_detail}"
                )
            interface_negative_details[label] = mutant_detail

    # A one-output Yosys miter may name the output equality itself
    # ``outputs_equal``.  This is a direct proof duty, not a disconnected
    # aggregate, and must be accepted.
    single_output_smt2 = r"""
(declare-fun |miter#0| (|miter_s|) (_ BitVec 8)) ; \gold_out1
(declare-fun |miter#1| (|miter_s|) (_ BitVec 8)) ; \gate_out1
(define-fun |miter#6| ((state |miter_s|)) Bool (= (|miter#1| state) (|miter#0| state))) ; \outputs_equal
(define-fun |miter#7| ((state |miter_s|)) (_ BitVec 1) (ite (|miter#6| state) #b0 #b1)) ; $assert$single_EN
; yosys-smt2-assert 0 $assert$single single.sv:1.1-1.2
(define-fun |miter_a 0| ((state |miter_s|)) Bool (or false (not (= ((_ extract 0 0) (|miter#7| state)) #b1)))) ; $assert$single
(define-fun |miter_a| ((state |miter_s|)) Bool (and
  (|miter_a 0| state)
))
""".strip()
    single_ok, single_detail = checker.audit_smt2_proof_duty(
        single_output_smt2, [("out1", 8)]
    )
    if not single_ok:
        raise AssertionError(f"Single-output proof duty rejected: {single_detail}")

    single_disconnected = single_output_smt2.replace(
        "(= (|miter#1| state) (|miter#0| state))", "true", 1
    )
    disconnected_ok, disconnected_detail = checker.audit_smt2_proof_duty(
        single_disconnected, [("out1", 8)]
    )
    if disconnected_ok:
        raise AssertionError(
            f"Disconnected single-output equality accepted: {disconnected_detail}"
        )

    # Three or more output equalities are commonly serialized through a
    # balanced Boolean tree.  Every leaf must be reachable from the aggregate.
    three_output_smt2 = r"""
(declare-fun |miter#0| (|miter_s|) (_ BitVec 8)) ; \gate_out1
(declare-fun |miter#1| (|miter_s|) (_ BitVec 8)) ; \gate_out2
(declare-fun |miter#2| (|miter_s|) (_ BitVec 8)) ; \gate_out3
(declare-fun |miter#3| (|miter_s|) (_ BitVec 8)) ; \gold_out1
(declare-fun |miter#4| (|miter_s|) (_ BitVec 8)) ; \gold_out2
(declare-fun |miter#5| (|miter_s|) (_ BitVec 8)) ; \gold_out3
(define-fun |miter#11| ((state |miter_s|)) Bool (= (|miter#3| state) (|miter#0| state))) ; $eq$out1
(define-fun |miter#12| ((state |miter_s|)) Bool (= (|miter#4| state) (|miter#1| state))) ; $eq$out2
(define-fun |miter#13| ((state |miter_s|)) Bool (and (|miter#11| state) (|miter#12| state))) ; $logic_and$pair
(define-fun |miter#14| ((state |miter_s|)) Bool (= (|miter#5| state) (|miter#2| state))) ; $eq$out3
(define-fun |miter#15| ((state |miter_s|)) Bool (and (|miter#13| state) (|miter#14| state))) ; \outputs_equal
(define-fun |miter#16| ((state |miter_s|)) (_ BitVec 1) (ite (|miter#15| state) #b0 #b1)) ; $assert$three_EN
; yosys-smt2-assert 0 $assert$three three.sv:1.1-1.2
(define-fun |miter_a 0| ((state |miter_s|)) Bool (or false (not (= ((_ extract 0 0) (|miter#16| state)) #b1)))) ; $assert$three
(define-fun |miter_a| ((state |miter_s|)) Bool (and
  (|miter_a 0| state)
))
""".strip()
    three_ok, three_detail = checker.audit_smt2_proof_duty(
        three_output_smt2, [("out1", 8), ("out2", 8), ("out3", 8)]
    )
    if not three_ok:
        raise AssertionError(f"Three-output proof duty rejected: {three_detail}")

    tree_disconnect = three_output_smt2.replace(
        "(and (|miter#11| state) (|miter#12| state))",
        "(and (|miter#11| state) true)",
        1,
    )
    tree_ok, tree_detail = checker.audit_smt2_proof_duty(
        tree_disconnect, [("out1", 8), ("out2", 8), ("out3", 8)]
    )
    if tree_ok or "missing_miter#12" not in tree_detail:
        raise AssertionError(f"Disconnected equality-tree leaf accepted: {tree_detail}")

    # Synthetic complete three-output SMT fixture; no archived benchmark evidence.
    smt2 = three_output_smt2
    outputs = [("out1", 8), ("out2", 8), ("out3", 8)]

    genuine_ok, genuine_detail = checker.audit_smt2_proof_duty(smt2, outputs)
    if not genuine_ok:
        raise AssertionError(f"Genuine proof duty rejected: {genuine_detail}")

    aggregate = balanced_definition(smt2, "(define-fun |miter_a|")
    assertion_refs = re.findall(r"\(\|(miter_a \d+)\| state\)", aggregate)
    if not assertion_refs:
        raise AssertionError("Aggregate assertion contains no per-assertion reference")
    disconnected_aggregate = aggregate.replace(
        f"(|{assertion_refs[0]}| state)", "true", 1
    )
    aggregate_mutant = smt2.replace(aggregate, disconnected_aggregate, 1)
    aggregate_ok, aggregate_detail = checker.audit_smt2_proof_duty(
        aggregate_mutant, outputs
    )
    if aggregate_ok or "aggregate_missing" not in aggregate_detail:
        raise AssertionError(f"Disconnected aggregate was accepted: {aggregate_detail}")

    marker = next(line for line in smt2.splitlines() if "; yosys-smt2-assert" in line)
    marker_mutant = smt2.replace(marker, "", 1)
    marker_ok, marker_detail = checker.audit_smt2_proof_duty(marker_mutant, outputs)
    if marker_ok:
        raise AssertionError(f"Missing assertion marker was accepted: {marker_detail}")

    outputs_equal = next(
        line for line in smt2.splitlines() if "; \\outputs_equal" in line
    )
    equality_refs = re.findall(r"\(\|(miter#\d+)\| state\)", outputs_equal)
    if not equality_refs:
        raise AssertionError("outputs_equal contains no equality reference")
    equality_mutant = outputs_equal.replace(
        f"(|{equality_refs[0]}| state)", "true", 1
    )
    equality_text = smt2.replace(outputs_equal, equality_mutant, 1)
    equality_ok, equality_detail = checker.audit_smt2_proof_duty(
        equality_text, outputs
    )
    if equality_ok:
        raise AssertionError(f"Disconnected output equality was accepted: {equality_detail}")

    print(
        json.dumps(
            {
                "status": "pass",
                "abc_timeout_precedence": abc_timeout[0],
                "smt_timeout_precedence": smt_timeout[0],
                "abc_cancellation_precedence": abc_cancelled[0],
                "abc_conclusive_conflict": conflict_result.status,
                "abc_pass_plus_unknown": pass_with_unknown.status,
                "interface_contract_positive": "pass",
                "interface_contract_negatives": interface_negative_details,
                "single_output": single_detail,
                "single_output_disconnect": disconnected_detail,
                "three_output_tree": three_detail,
                "three_output_tree_disconnect": tree_detail,
                "genuine": genuine_detail,
                "aggregate_disconnect": aggregate_detail,
                "marker_removal": marker_detail,
                "output_equality_disconnect": equality_detail,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


import unittest

class SyntheticRegression(unittest.TestCase):
    def test_synthetic_regression(self):
        main()

if __name__ == "__main__":
    raise SystemExit(main())

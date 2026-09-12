#!/usr/bin/env python3
"""Real-Yosys regressions for significance-sliced algebraic CEC."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import tool_path
ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "skills/circuit-reverse-rtl/scripts/verify/cec.py"
YOSYS = tool_path("yosys")

REFERENCE = """module top(a, b, y);
input [1:0] a, b;
output [2:0] y;
wire c0, t0, t1, t2, c1;
xor g0(y[0], a[0], b[0]);
and g1(c0, a[0], b[0]);
xor g2(y[1], a[1], b[1], c0);
and g3(t0, a[1], b[1]);
and g4(t1, a[1], c0);
and g5(t2, b[1], c0);
or g6(c1, t0, t1, t2);
buf g7(y[2], c1);
endmodule
"""

CONDITION_REFERENCE = """module top(a, b, s, y0, y1, y2);
input a, b;
input [1:0] s;
output [0:0] y0, y1, y2;
wire gt1, nz, eq3, ngt1, nnz, neq3;
wire gt_a, gt_b, nz_a, nz_b, eq_a, eq_b;
buf g0(gt1, s[1]);
or g1(nz, s[0], s[1]);
and g2(eq3, s[0], s[1]);
not g3(ngt1, gt1);
not g4(nnz, nz);
not g5(neq3, eq3);
and g6(gt_a, gt1, a);
and g7(gt_b, ngt1, b);
or g8(y0[0], gt_a, gt_b);
and g9(nz_a, nz, a);
and g10(nz_b, nnz, b);
or g11(y1[0], nz_a, nz_b);
and g12(eq_a, eq3, a);
and g13(eq_b, neq3, b);
or g14(y2[0], eq_a, eq_b);
endmodule
"""


class SlicedAlgebraicAudit(unittest.TestCase):
    def run_case(self, expression):
        with tempfile.TemporaryDirectory(prefix="sliced_algebraic_audit_") as name:
            folder = Path(name)
            reference = folder / "reference.v"
            candidate = folder / "candidate.v"
            reference.write_text(REFERENCE)
            candidate.write_text(
                "module top(a, b, y);\n"
                "input [1:0] a, b;\n"
                "output [2:0] y;\n"
                f"assign y = {expression};\n"
                "endmodule\n"
            )
            result = subprocess.run(
                ["python3", str(CHECKER), str(reference), str(candidate),
                 "--engine", "algebraic", "--yosys", str(YOSYS),
                 "--algebraic-sliced-output", "y", "--algebraic-timeout", "20",
                 "--keep-tmp", "--tmpdir", str(folder / "artifacts"), "--json"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            return json.loads(result.stdout)

    def run_condition_case(self, expressions):
        with tempfile.TemporaryDirectory(prefix="condition_algebraic_audit_") as name:
            folder = Path(name)
            reference = folder / "reference.v"
            candidate = folder / "candidate.v"
            reference.write_text(CONDITION_REFERENCE)
            candidate.write_text(
                "module top(a, b, s, y0, y1, y2);\n"
                "input a, b;\n"
                "input [1:0] s;\n"
                "output [0:0] y0, y1, y2;\n"
                f"assign y0 = {expressions[0]};\n"
                f"assign y1 = {expressions[1]};\n"
                f"assign y2 = {expressions[2]};\n"
                "endmodule\n"
            )
            result = subprocess.run(
                ["python3", str(CHECKER), str(reference), str(candidate),
                 "--engine", "algebraic", "--yosys", str(YOSYS),
                 "--algebraic-sliced-output", "y0",
                 "--algebraic-sliced-output", "y1",
                 "--algebraic-sliced-output", "y2",
                 "--algebraic-case-split-bit", "s[0]",
                 "--algebraic-case-split-bit", "s[1]", "--algebraic-timeout", "20",
                 "--keep-tmp", "--tmpdir", str(folder / "artifacts"), "--json"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            records = list(folder.glob("artifacts/*/proof/independent_replay/record.json"))
            return result, json.loads(records[0].read_text()) if len(records) == 1 else None

    def test_equivalent_adder_has_complete_certificate(self):
        result = self.run_case("{1'b0, a} + {1'b0, b}")
        self.assertEqual(result["status"], "pass")
        self.assertIs(result["equivalent"], True)

    def test_add_one_mutation_never_passes(self):
        result = self.run_case("{1'b0, a} + {1'b0, b} + 1'b1")
        self.assertNotEqual(result["status"], "pass")
        self.assertIsNot(result["equivalent"], True)

    def test_small_comparison_conditions_have_complete_certificates(self):
        completed, record = self.run_condition_case([
            "(s > 1) ? a : b", "s ? a : b", "(s == 2'd3) ? a : b"
        ])
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass", completed.stderr)
        self.assertIs(result["equivalent"], True)
        checks = [check for output in record["outputs"].values()
                  for check in output["candidate_condition_truth_table_certificates"]]
        self.assertEqual({item["cell_type"] for item in checks}, {"$eq", "$gt", "$reduce_bool"})
        self.assertTrue(all(item["assignments_checked"] == 4 for item in checks))
        self.assertIs(record["case_split_complete_boolean_cube"], True)
        self.assertEqual(record["case_split_branch_count"], 4)
        self.assertTrue(all(len(output["case_split_branches"]) == 4
                            for output in record["outputs"].values()))

    def test_comparison_condition_mutation_never_passes(self):
        completed, _ = self.run_condition_case([
            "(s > 1) ? a : b", "s ? a : b", "(s == 2'd2) ? a : b"
        ])
        result = json.loads(completed.stdout)
        self.assertNotEqual(result["status"], "pass")
        self.assertIsNot(result["equivalent"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

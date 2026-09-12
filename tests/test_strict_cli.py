"""Fresh synthetic complete-interface proofs through both public solver routes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CEC = ROOT / "skills/circuit-reverse-rtl/scripts/cec.py"


class StrictCLI(unittest.TestCase):
    def check(self, engine, mutant=False):
        with tempfile.TemporaryDirectory(prefix="release_strict_") as temp:
            directory = Path(temp)
            reference = directory / "reference.v"
            candidate = directory / "candidate.v"
            reference.write_text("module top(input [2:0] a, b, output [3:0] y, output z); "
                                 "assign y={1'b0,a}+{1'b0,b}; assign z=^a; endmodule\n")
            candidate.write_text("module top(input [2:0] a, b, output [3:0] y, output z); "
                                 "assign y={1'b0,b}+{1'b0,a}; assign z="
                                 + ("~" if mutant else "") + "(a[0]^a[1]^a[2]); endmodule\n")
            result = subprocess.run(
                [sys.executable, str(CEC), str(reference), str(candidate),
                 "--engine", engine, "--strict-cec", "--timeout", "20",
                 "--abc-timeout", "20", "--smt-timeout", "20", "--json"],
                capture_output=True, text=True, timeout=60,
            )
            try:
                record = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.fail(f"CEC did not return JSON: {result.stdout}\n{result.stderr}")
            self.assertEqual(record["status"], "fail" if mutant else "pass", record)
            self.assertEqual(record["equivalent"], not mutant, record)

    def test_strict_abc_complete_interface(self):
        self.check("cec")

    def test_strict_abc_last_output_mutation(self):
        self.check("cec", mutant=True)

    def test_strict_smt_complete_interface(self):
        self.check("smt")

    def test_strict_smt_last_output_mutation(self):
        self.check("smt", mutant=True)


if __name__ == "__main__":
    unittest.main()

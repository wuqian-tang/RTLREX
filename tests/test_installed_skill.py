"""A copied single Skill must run its own nested coefficient checker."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstalledSkill(unittest.TestCase):
    def test_terminal_proof_from_standalone_install_and_foreign_cwd(self):
        with tempfile.TemporaryDirectory(prefix="installed-skill-test-") as temp:
            directory = Path(temp)
            installed = directory / "custom-skill-location"
            subprocess.run([sys.executable, str(ROOT / "scripts/install.py"),
                            "--dest", str(installed)],
                           check=True, capture_output=True, text=True, timeout=20)
            foreign = directory / "unrelated-working-directory"
            foreign.mkdir()
            reference = foreign / "reference.v"
            candidate = foreign / "candidate.v"
            header = "module top(a,y); input [6:0] a; output [0:0] y; "
            reference.write_text(header + "xor g(y[0], " +
                                 ",".join(f"a[{i}]" for i in range(7)) + "); endmodule\n")
            candidate.write_text(header + "assign y=" +
                                 "+".join(f"a[{i}]" for i in range(7)) + "; endmodule\n")
            proof = directory / "proof"
            command = [sys.executable, str(installed / "scripts/cec.py"),
                       str(reference), str(candidate), "--engine", "algebraic-terminal",
                       "--strict-cec", "--algebraic-coefficient-input", "a",
                       "--algebraic-timeout", "30", "--keep-tmp", "--tmpdir", str(proof), "--json"]
            process = subprocess.run(command, cwd=foreign, capture_output=True,
                                     text=True, timeout=45)
            result = json.loads(process.stdout)
            self.assertEqual(result["status"], "pass", result)
            self.assertTrue(result["equivalent"])
            nested = list(proof.rglob("coefficient_command.json"))
            self.assertEqual(len(nested), 1)
            invocation = json.loads(nested[0].read_text())
            self.assertTrue(Path(invocation[1]).is_relative_to(installed), invocation)
            self.assertEqual(Path(invocation[1]).name, "cec.py")


if __name__ == "__main__":
    unittest.main()

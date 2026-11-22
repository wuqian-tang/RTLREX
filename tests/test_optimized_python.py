"""Disabled Python assertions must never weaken public proof checking."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/circuit-reverse-rtl/scripts"


class OptimizedPythonGuard(unittest.TestCase):
    def check_entrypoints(self, flag=False):
        environment = os.environ.copy()
        if not flag:
            environment["PYTHONOPTIMIZE"] = "1"
        for relative in ["cec.py", "verify/grouped_algebraic.py", "verify/typed_product.py"]:
            with self.subTest(entrypoint=relative):
                process = subprocess.run(
                    [sys.executable, *(["-O"] if flag else []), str(SCRIPTS / relative), "--help"],
                    env=environment, capture_output=True, text=True, timeout=10,
                )
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("assertions enabled", process.stderr)
                self.assertIn("PYTHONOPTIMIZE", process.stderr)

    def test_python_o_rejected(self):
        self.check_entrypoints(flag=True)

    def test_pythonoptimize_environment_rejected(self):
        self.check_entrypoints()


if __name__ == "__main__":
    unittest.main()

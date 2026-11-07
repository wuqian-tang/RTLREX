"""Large published RTL must retain byte identity and credential scanning."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

class ReleaseScanTests(unittest.TestCase):
    def fixture(self,root):
        (root/'scripts').mkdir();shutil.copyfile(ROOT/'scripts/check_release.py',root/'scripts/check_release.py')
        package=root/'experiments/tt100-final';(package/'rtl/with_skill').mkdir(parents=True)
        candidate=package/'rtl/with_skill/ex299.v';candidate.write_text('// generated\n'+' '*2_000_001)
        with (package/'case_results.csv').open('w') as f:
            writer=csv.DictWriter(f,fieldnames=['case','arm','candidate_sha256']);writer.writeheader();writer.writerow(dict(case='ex299',arm='with_skill',candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest()))
        return candidate
    def scan(self,root):
        return subprocess.run([sys.executable,str(root/'scripts/check_release.py')],capture_output=True,text=True)
    def test_exact_large_terminal_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root);r=self.scan(root)
            self.assertEqual(r.returncode,0,r.stdout)
    def test_modified_large_terminal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.fixture(root);p.write_text(p.read_text()+'changed');r=self.scan(root)
            self.assertNotEqual(r.returncode,0)
    def test_allowlisted_large_file_still_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.fixture(root);p.write_text(p.read_text()+'\n'+'gh'+'p_'+'x'*36)
            with (root/'experiments/tt100-final/case_results.csv').open('w') as f:
                writer=csv.DictWriter(f,fieldnames=['case','arm','candidate_sha256']);writer.writeheader();writer.writerow(dict(case='ex299',arm='with_skill',candidate_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
            r=self.scan(root);self.assertNotEqual(r.returncode,0);self.assertIn('credential',r.stdout)

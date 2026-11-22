"""Dependency diagnostics must reflect the executable choices used by tools."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('YOSYS', 'ABC', 'YOSYS_SMTBMC', 'IVERILOG', 'VVP', 'CXX')

class DoctorTests(unittest.TestCase):
    def run_doctor(self, env):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/doctor.py'), '--require-all'],
                                env=env, capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def test_explicit_tools_outside_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / 'configured-tool'
            tool.write_text('#!/bin/sh\nexit 0\n')
            tool.chmod(0o755)
            z3 = Path(tmp) / 'z3'
            z3.write_text('#!/bin/sh\nexit 0\n')
            z3.chmod(0o755)
            env = {**os.environ, 'PATH': tmp, **{k: str(tool) for k in KEYS}}
            status, report = self.run_doctor(env)
            self.assertEqual(status, 0)
            self.assertTrue(all(report['tools'][k] == str(tool) for k in KEYS))
            self.assertEqual(report['tools']['Z3'], str(z3))

    def test_invalid_override_never_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in ('yosys', 'abc', 'yosys-smtbmc', 'z3', 'iverilog', 'vvp', 'g++'):
                p = directory / name
                p.write_text('#!/bin/sh\nexit 0\n')
                p.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k not in KEYS}
            env['PATH'] = tmp
            for key in KEYS:
                with self.subTest(tool=key):
                    status, report = self.run_doctor({**env, key: str(directory / 'missing')})
                    self.assertNotEqual(status, 0)
                    self.assertIsNone(report['tools'][key])

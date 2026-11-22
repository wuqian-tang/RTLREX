"""Compile the native sampler and reject unsupported/undriven input formats."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativeSamplerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='native-sampler-tests-')
        cls.work = Path(cls.temp.name)
        cls.binary = cls.work / 'sampler'
        source = ROOT / 'skills/circuit-reverse-rtl/scripts/sampling/fast_primitive_sampler.cpp'
        subprocess.run(['g++', '-O2', '-std=c++17', str(source), '-o', str(cls.binary)],
                       check=True, capture_output=True, timeout=90)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_circuit(self, source):
        return subprocess.run([str(self.binary), str(source)], cwd=self.work,
                              input=''.join(f'x={i}\n' for i in range(8)),
                              text=True, capture_output=True, timeout=10)

    def test_complete_parity(self):
        result = self.run_circuit(ROOT / 'examples/parity/reference.v')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         [f'y={i.bit_count() % 2}' for i in range(8)])

    def test_ansi_header_rejected(self):
        source = self.work / 'ansi.v'
        source.write_text('module top(input [2:0] x, output y);\n'
                          'assign y = ^x;\nendmodule\n')
        result = self.run_circuit(source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no supported output declarations', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_undriven_output_rejected(self):
        source = self.work / 'undriven.v'
        source.write_text('module top(x,y);\ninput [2:0] x;\noutput y;\nendmodule\n')
        result = self.run_circuit(source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('undriven or unsupported output cone', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()

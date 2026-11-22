"""Exact low-level fallback for complete truth tables."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVERSER = ROOT / 'skills/circuit-reverse-rtl/scripts/truth_reverse.py'


class TruthBooleanFallbackTests(unittest.TestCase):
    def test_unmatched_majority_gets_exact_low_level_certificate(self):
        with tempfile.TemporaryDirectory(prefix='truth-fallback-test-') as temp_name:
            temp = Path(temp_name)
            truth = temp / 'majority.truth'
            # Three-input majority in ABC read_truth -xf storage order.
            truth.write_text('11101000\n')
            output = temp / 'majority.v'
            result = subprocess.run(
                [sys.executable, str(REVERSER), str(truth), str(output),
                 '--allow-boolean-fallback', '--verify', '--json'],
                cwd=temp, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual(record['status'], 'generated', record)
            self.assertEqual(record['verify'], 'pass', record)
            self.assertFalse(record['high_level'], record)
            self.assertIn(record['family'], {'structural ANF fallback', 'shared ROBDD fallback'})
            certificate = Path(record['certificate'])
            proof = json.loads(certificate.read_text())
            self.assertTrue(proof['strict'], proof)
            self.assertEqual(proof['vectors_checked'], 8)
            self.assertEqual(proof['output_bits_checked'], 1)


if __name__ == '__main__':
    unittest.main()

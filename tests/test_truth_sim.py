"""Real Icarus replay: exact row coverage, bad values and unexpected output."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'skills/circuit-reverse-rtl/scripts/verify_truth_sim.py'
TRUTH = ROOT / 'examples/parity/parity.truth'


class TruthReplayTests(unittest.TestCase):
    def check(self, body, expected_status):
        with tempfile.TemporaryDirectory(prefix='truth-replay-test-') as temp:
            candidate = Path(temp) / 'candidate.v'
            candidate.write_text('module top(input [2:0] x, output y);\n'
                                 + body + '\nendmodule\n')
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(TRUTH), str(candidate), '--json'],
                cwd=temp, capture_output=True, text=True, timeout=30,
            )
            record = json.loads(result.stdout)
            self.assertEqual(record['status'], expected_status, record)
            self.assertEqual(result.returncode, 0 if expected_status == 'pass' else 1)
            return record

    def test_complete_replay_has_exactly_eight_rows(self):
        result = self.check('assign y = ^x;', 'pass')
        self.assertEqual(result['vectors'], 8)

    def test_wrong_output_rejected(self):
        self.check('assign y = ~(^x);', 'mismatch')

    def test_early_finish_rejected(self):
        self.check('assign y = ^x;\ninitial begin #3; $finish(0); end', 'short_output')

    def test_extra_output_is_not_silently_discarded(self):
        self.check('assign y = ^x;\ninitial $display("unexpected output");', 'short_output')


if __name__ == '__main__':
    unittest.main()

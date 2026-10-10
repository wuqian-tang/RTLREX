#!/usr/bin/env python3
"""Regression tests for shared classification and signed fixed-point factoring."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from reverse import truth_reverse as reverse
from truth.fixed_point_compact import compact_fixed_point_operators
from truth.utils import read_truth_words


def write_words(path: Path, n: int, m: int, words: list[int]) -> None:
    # The first character corresponds to the complemented all-zero input.
    mask = (1 << n) - 1
    path.write_text('\n'.join(''.join(str((words[index ^ mask] >> bit) & 1)
                                    for index in range(1 << n))
                             for bit in range(m)) + '\n')


class SharedDescriptionTests(unittest.TestCase):
    def test_words_api_handles_multiple_input_widths(self):
        for n in (4, 8, 12):
            half = n // 2
            words = [(x & ((1 << half) - 1)) * (x >> half) for x in range(1 << n)]
            candidate = reverse.infer_from_words(n, n, words)
            self.assertIsNotNone(candidate)
            self.assertIn('*', candidate.verilog)
            self.assertIn(f'input [{n-1}:0] x', candidate.verilog)
            self.assertIn(f'output [{n-1}:0] y', candidate.verilog)
            # Family wording changed when the general quadratic model gained
            # multiplication; verify the emitted word semantics instead.
            from verify.truth_yosys import default_yosys, verify
            with tempfile.TemporaryDirectory() as temporary:
                truth, rtl = Path(temporary) / 'words.truth', Path(temporary) / 'words.v'
                write_words(truth, n, n, words)
                rtl.write_text(candidate.verilog)
                proof = verify(truth, rtl, default_yosys(), use_cache=False)
                self.assertEqual(proof['status'], 'pass', proof)
                self.assertEqual(proof['frontend'], 'pass')
                self.assertEqual(proof['vectors'], 1 << n)

    def test_no_match_description_is_not_recomputed(self):
        words = [0, 1, 3, 2]
        with patch.object(reverse, 'STRUCTURAL_MATCHERS',
                          (reverse.try_float_simple_structured, reverse.try_float_sqrt_structured)), \
             patch.object(reverse, 'describe_truth', return_value=None) as describe:
            self.assertIsNone(reverse.infer_from_words(2, 2, words))
            self.assertEqual(describe.call_count, 1)
            describe.reset_mock()
            self.assertIsNone(reverse.infer_from_words(2, 2, words, description=None))
            describe.assert_not_called()

    def test_process_reads_and_describes_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            truth = Path(temporary) / 'toy.truth'
            write_words(truth, 4, 4, [i * i & 15 for i in range(16)])
            args = SimpleNamespace(allow_field_cases=False, allow_boolean_fallback=False,
                                   output=str(Path(temporary) / 'output.v'), out_dir=temporary,
                                   flat=True, verify=False, verify_yosys=False)
            with patch.object(reverse, 'read_truth_words', wraps=read_truth_words) as read, \
                 patch.object(reverse, 'describe_truth', return_value=None) as describe:
                result = reverse.process_one(truth, args)
                self.assertEqual(result['status'], 'generated')
                self.assertEqual(read.call_count, 1)
                self.assertEqual(describe.call_count, 1)


class SignedKernelTests(unittest.TestCase):
    def test_mixed_width_prefix_is_preserved(self):
        rtl = 'module top;\n  always @(*) begin\n    wide = a * b;\n    narrow = c + d;\n  end\nendmodule\n'
        changed = compact_fixed_point_operators(rtl, width=4,
                                                body_start='    narrow =')
        self.assertIn('    wide = a * b;', changed)
        self.assertIn('    narrow = fp_add(c, d);', changed)
        self.assertEqual(compact_fixed_point_operators(rtl, body_start='absent'), rtl)
        duplicated = rtl.replace('    narrow = c + d;', '    narrow = c + d;\n    narrow = a + b;')
        self.assertEqual(compact_fixed_point_operators(duplicated, body_start='    narrow ='), duplicated)

    def test_unsupported_expression_remains_unchanged(self):
        rtl = 'module top;\n  always @(*) begin\n    y = a ^ b;\n  end\nendmodule\n'
        self.assertEqual(compact_fixed_point_operators(rtl), rtl)

    def test_configured_widths_exhaustive_after_yosys(self):
        from verify.tooling import optional_tool
        discovered = optional_tool('YOSYS')
        if discovered is None:
            self.skipTest('Yosys is not installed')
        yosys = Path(discovered)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for width in (4, 6, 8):
                n = 2 * width
                mask = (1 << width) - 1
                def signed(value):
                    return value - (1 << width) if value & (1 << (width-1)) else value
                words = []
                for x in range(1 << n):
                    a, b = signed(x & mask), signed(x >> width)
                    words.append((a * b + (a >> 1 if a < 0 else b)) & mask)
                rtl = f'''module top(input [{n-1}:0] x, output reg [{width-1}:0] y);
  reg signed [{width-1}:0] a, b;
  always @(*) begin
    a = x[{width-1}:0];
    b = x[{n-1}:{width}];
    y = (a * b) + ((a < 0) ? (a >>> 1) : b);
  end
endmodule
'''
                truth, candidate = base / f'w{width}.truth', base / f'w{width}.v'
                write_words(truth, n, width, words)
                candidate.write_text(compact_fixed_point_operators(rtl, width=width))
                result = subprocess.run([sys.executable, str(SCRIPTS / 'verify_truth_yosys.py'),
                                         str(truth), str(candidate), '--yosys', str(yosys),
                                         '--no-cache', '--json'], capture_output=True, text=True,
                                        timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                certificate = json.loads(result.stdout)
                self.assertEqual(certificate['status'], 'pass')
                self.assertEqual(certificate['frontend'], 'pass')


if __name__ == '__main__':
    unittest.main()

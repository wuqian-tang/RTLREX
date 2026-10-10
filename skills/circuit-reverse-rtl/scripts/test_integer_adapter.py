#!/usr/bin/env python3
"""Independent signed-width and narrow-result checks for integer RTL models."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from reverse import truth_reverse as reverse
from test_fixed_point_compact import write_words


def signed(value: int, width: int) -> int:
    return value - (1 << width) if value & (1 << (width - 1)) else value


class IntegerAdapterTests(unittest.TestCase):
    def test_fast_multiplier_precedes_generic_integer_then_float(self):
        matchers = reverse.STRUCTURAL_MATCHERS
        self.assertLess(matchers.index(reverse.try_affine), matchers.index(reverse.try_integer_model))
        self.assertLess(matchers.index(reverse.try_unsigned_mul), matchers.index(reverse.try_integer_model))
        self.assertLess(matchers.index(reverse.try_integer_model), matchers.index(reverse.try_float_simple_structured))

    def test_wider_signed_arithmetic_and_native_width_comparisons(self):
        from verify.truth_yosys import default_yosys
        yosys = default_yosys()
        self.assertIsNotNone(yosys, 'fixed configured Yosys must be present')
        specifications = []
        for n, m in ((3, 9), (5, 12), (7, 13)):
            specifications.append((f'signed_affine_{n}_{m}', n, m,
                                   lambda x, n=n: -7 * signed(x, n) + 19))
        # Unequal native widths and one-bit fields test sign-extension as well
        # as comparison sizing independent of the assignment result width.
        for low_width, high_width in ((1, 4), (2, 5), (5, 2)):
            n = low_width + high_width
            def parts(x, low_width=low_width, high_width=high_width):
                return signed(x & ((1 << low_width) - 1), low_width), signed(x >> low_width, high_width)
            for m in (1, 3, n + 4):
                specifications.append((f'signed_min_{low_width}_{high_width}_{m}', n, m,
                                       lambda x, parts=parts: min(parts(x))))
                specifications.append((f'signed_max_{low_width}_{high_width}_{m}', n, m,
                                       lambda x, parts=parts: max(parts(x))))
            specifications.append((f'signed_lt_{low_width}_{high_width}', n, 1,
                                   lambda x, parts=parts: int(parts(x)[0] < parts(x)[1])))
            specifications.append((f'mixed_affine_{low_width}_{high_width}', n, n + 4,
                                   lambda x, low_width=low_width, parts=parts:
                                       11 * parts(x)[0] - 3 * (x >> low_width) - 17))
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, n, m, model in specifications:
                with self.subTest(name=name):
                    words = [model(x) & ((1 << m) - 1) for x in range(1 << n)]
                    candidate = reverse.try_integer_model(n, m, words)
                    self.assertIsNotNone(candidate, name)
                    self.assertTrue(candidate.high_level)
                    truth, rtl = base / f'{name}.truth', base / f'{name}.v'
                    write_words(truth, n, m, words)
                    rtl.write_text(candidate.verilog)
                    result = subprocess.run(
                        [sys.executable, str(SCRIPTS / 'verify_truth_yosys.py'),
                         str(truth), str(rtl), '--yosys', str(yosys), '--no-cache', '--json'],
                        capture_output=True, text=True, timeout=120)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    certificate = json.loads(result.stdout)
                    self.assertEqual(certificate['frontend'], 'pass')
                    self.assertEqual(certificate['status'], 'pass')


if __name__ == '__main__':
    unittest.main()

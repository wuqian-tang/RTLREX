"""Independent rational-oracle controls for unsigned packed fixed-point dots."""
from bisect import bisect_left
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import tempfile
import unittest

from truth.scaled_integer_dot_compact import emit_unsigned_scaled_dot
from verify.truth_yosys import verify, default_yosys


class ScaledDotReference:
    def __init__(self, width, fractional, lanes, oe=4, of=3):
        self.width, self.fractional, self.lanes = width, fractional, lanes
        self.oe, self.of = oe, of
        self.outputs = []
        bias = (1 << (oe - 1)) - 1
        for code in range((1 << (oe + of)) - 1):
            exponent, fraction = divmod(code, 1 << of)
            self.outputs.append((Fraction(1) + Fraction(fraction, 1 << of)) * Fraction(2) ** (exponent - bias)
                                if exponent else Fraction(fraction, 1 << of) * Fraction(2) ** (1 - bias))

    @lru_cache(maxsize=None)
    def nearest(self, quarter_value):
        value = Fraction(quarter_value, 1 << (2 * self.fractional))
        index = bisect_left(self.outputs, value)
        if index == 0:
            return 0
        if index == len(self.outputs):
            return index - 1
        return min((index - 1, index), key=lambda code: (abs(self.outputs[code] - value), code % 2))

    def word(self, value):
        mask = (1 << self.width) - 1
        total = sum(((value >> (index * self.width)) & mask) *
                    ((value >> ((index + self.lanes) * self.width)) & mask)
                    for index in range(self.lanes))
        return self.nearest(total)


def check(reference, source):
    n_inputs = 2 * reference.width * reference.lanes
    words = [reference.word(value) for value in range(1 << n_inputs)]
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        truth, candidate = directory / 'input.truth', directory / 'candidate.v'
        mask = len(words) - 1
        truth.write_text('\n'.join(''.join(str((words[value ^ mask] >> bit) & 1)
                                         for value in range(len(words)))
                                   for bit in range(1 + reference.oe + reference.of)) + '\n')
        candidate.write_text(source)
        return verify(truth, candidate, default_yosys(), use_cache=False,
                      frontend_timeout=120, compile_timeout=120, run_timeout=180)


class ScaledIntegerDotTests(unittest.TestCase):
    def test_full_nonbenchmark_format_and_lane_domains(self):
        formats = [(1, 0, 3, 4, 3), (2, 0, 2, 4, 3), (3, 1, 2, 4, 3),
                   (2, 2, 3, 5, 2), (3, 3, 2, 5, 2)]
        for w, f, lanes, oe, of in formats:
            with self.subTest(format=(w, f, lanes, oe, of)):
                reference = ScaledDotReference(w, f, lanes, oe, of)
                result = check(reference, emit_unsigned_scaled_dot(w, f, lanes, 'rational control', oe, of))
                self.assertEqual(result['frontend'], 'pass', result)
                self.assertEqual(result['status'], 'pass', result)
                self.assertEqual(result['vectors'], 1 << (2 * w * lanes))

    def test_wrong_pairing_and_rounding_mutations_are_rejected(self):
        reference = ScaledDotReference(3, 1, 2, 4, 2)
        source = emit_unsigned_scaled_dot(3, 1, 2, 'independent mutation control', 4, 2)
        mutations = [source.replace('lane(x, index + 2)', 'lane(x, index)'),
                     source.replace(' - 1, value[shift])', " - 1, 1'b0)")]
        for mutation in mutations:
            self.assertNotEqual(source, mutation)
            result = check(reference, mutation)
            self.assertEqual(result['frontend'], 'pass', result)
            self.assertEqual(result['status'], 'mismatch', result)

    def test_midpoint_and_carry_boundaries(self):
        reference = ScaledDotReference(3, 1, 2)
        self.assertEqual(reference.nearest(0), 0)
        self.assertEqual(reference.nearest(33), reference.nearest(32))
        self.assertEqual(reference.nearest(35), reference.nearest(36))
        self.assertEqual(reference.nearest(63), reference.nearest(64))
        self.assertEqual(reference.nearest(98), 92)

    def test_bad_or_unbounded_contracts_fail_closed(self):
        for args in [(0, 0, 2), (2, -1, 2), (2, 3, 2), (2, 1, 0), (True, 0, 2), (2, 1, 1.5)]:
            with self.assertRaises(ValueError):
                emit_unsigned_scaled_dot(*args, 'invalid contract')
        with self.assertRaises(ValueError):
            emit_unsigned_scaled_dot(2, 2, 4, 'underflow handling required', 2, 2)
        with self.assertRaises(ValueError):
            emit_unsigned_scaled_dot(3, 0, 4, 'saturation handling required', 2, 2)


if __name__ == '__main__':
    unittest.main()

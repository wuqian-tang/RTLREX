"""Independent exact-rational and mutation controls for finite packed dots."""
from bisect import bisect_left
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import tempfile
import unittest

from truth.packed_float_compact import emit_finite_float_dot
from verify.truth_yosys import verify, default_yosys


def decode_lane(code, exponent_bits, fraction_bits):
    magnitude = code % (1 << (exponent_bits + fraction_bits))
    exponent, fraction = divmod(magnitude, 1 << fraction_bits)
    bias = (1 << (exponent_bits - 1)) - 1
    if exponent:
        number = Fraction(1) + Fraction(fraction, 1 << fraction_bits)
        number *= Fraction(2) ** (exponent - bias)
    else:
        number = Fraction(fraction, 1 << fraction_bits) * Fraction(2) ** (1 - bias)
    return -number if code >> (exponent_bits + fraction_bits) else number


class RationalReference:
    def __init__(self, e, f, lanes, oe=4, of=3):
        self.e, self.f, self.lanes, self.oe, self.of = e, f, lanes, oe, of
        self.width = 1 + e + f
        self.values = [decode_lane(code, e, f) for code in range(1 << self.width)]
        self.outputs = [decode_lane(code, oe, of) for code in range((1 << (oe + of)) - 1)]

    @lru_cache(maxsize=None)
    def nearest(self, value):
        index = bisect_left(self.outputs, value)
        if index == 0:
            return 0
        if index == len(self.outputs):
            return index - 1
        return min((index - 1, index), key=lambda code: (abs(self.outputs[code] - value), code % 2))

    def word(self, value):
        mask = (1 << self.width) - 1
        total = Fraction(0)
        all_negative = True
        for index in range(self.lanes):
            a = (value >> (index * self.width)) & mask
            b = (value >> ((index + self.lanes) * self.width)) & mask
            total += self.values[a] * self.values[b]
            all_negative &= bool((a >> (self.width - 1)) != (b >> (self.width - 1)))
        negative = (total < 0) or (total == 0 and all_negative)
        return (int(negative) << (self.oe + self.of)) | self.nearest(abs(total))


def check(reference, source):
    width = 2 * reference.width * reference.lanes
    words = [reference.word(value) for value in range(1 << width)]
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


class PackedFloatTests(unittest.TestCase):
    def test_full_nonbenchmark_format_and_lane_domains(self):
        formats = [(1, 1, 1, 4, 3), (2, 0, 2, 4, 3),
                   (1, 2, 2, 4, 3), (2, 1, 1, 5, 2), (1, 0, 3, 4, 3),
                   (1, 0, 1, 4, 5), (1, 0, 2, 4, 5), (1, 1, 1, 4, 5)]
        for e, f, lanes, oe, of in formats:
            with self.subTest(format=(e, f, lanes, oe, of)):
                reference = RationalReference(e, f, lanes, oe, of)
                source = emit_finite_float_dot(e, f, lanes, 'independent finite-format control', oe, of)
                result = check(reference, source)
                self.assertEqual(result['frontend'], 'pass', result)
                self.assertEqual(result['status'], 'pass', result)
                self.assertEqual(result['vectors'], 1 << (2 * reference.width * lanes))

    def test_negative_zero_and_rounding_mutations_are_rejected(self):
        reference = RationalReference(1, 2, 2, 5, 2)
        source = emit_finite_float_dot(1, 2, 2, 'independent rounding and signed-zero control', 5, 2)
        mutations = [source.replace('all_negative = 1;', 'all_negative = 0;'),
                     source.replace(' - 1, value[shift])', " - 1, 1'b0)")]
        for mutation in mutations:
            self.assertNotEqual(source, mutation)
            result = check(reference, mutation)
            self.assertEqual(result['frontend'], 'pass', result)
            self.assertEqual(result['status'], 'mismatch', result)

    def test_old_rounded_width_is_rejected(self):
        reference = RationalReference(1, 0, 1, 4, 5)
        source = emit_finite_float_dot(1, 0, 1, 'small bound wide fraction control', 4, 5)
        old_width = source.replace('reg [6:0] rounded;', 'reg [2:0] rounded;')
        self.assertNotEqual(source, old_width)
        result = check(reference, old_width)
        self.assertEqual(result['frontend'], 'pass', result)
        self.assertEqual(result['status'], 'mismatch', result)

    def test_exact_cancellation_and_all_zero_signs(self):
        reference = RationalReference(2, 1, 2)
        # Equal nonzero opposite products cancel to positive zero.
        self.assertEqual(reference.word(2 | (10 << 4) | (2 << 8) | (2 << 12)), 0)
        # Both zero products have negative sign, yielding negative zero.
        self.assertEqual(reference.word(8 | (8 << 4)), 128)
        # One positive zero product makes the exact zero sum positive.
        self.assertEqual(reference.word(8), 0)

    def test_format_and_range_contracts_fail_closed(self):
        for arguments in [(0, 1, 2), (2, -1, 2), (2, 1, 0), (True, 1, 2), (2, 1, 1.5)]:
            with self.assertRaises(ValueError):
                emit_finite_float_dot(*arguments, 'invalid contract')
        with self.assertRaises(ValueError):
            emit_finite_float_dot(2, 1, 2, 'output saturation is required', 2, 1)
        with self.assertRaises(ValueError):
            emit_finite_float_dot(4, 3, 2, 'output underflow is required', 4, 3)


if __name__ == '__main__':
    unittest.main()

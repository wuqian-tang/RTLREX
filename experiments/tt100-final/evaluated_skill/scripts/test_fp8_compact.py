"""Independent exact-rational FP8 contract and full-domain emitted-RTL checks."""
from __future__ import annotations
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path
import tempfile
import unittest

from truth.fp8_compact import emit_finite_fp8
from verify.truth_yosys import verify, default_yosys


class FiniteReference:
    """Nearest finite numeric value with ties to even; no emitted-RTL helpers."""
    def __init__(self, exponent, fraction):
        self.e, self.f = exponent, fraction
        self.scale = (1 << (exponent - 1)) - 1 + fraction - 1
        self.magnitudes = [self.decode(code) for code in range(127)]
        self.midpoints = [a + b for a, b in zip(self.magnitudes, self.magnitudes[1:])]
        self.square_midpoints = [midpoint * midpoint for midpoint in self.midpoints]

    def decode(self, code):
        exponent, fraction = (code & 127) >> self.f, code & ((1 << self.f) - 1)
        return fraction if exponent == 0 else ((1 << self.f) + fraction) << (exponent - 1)

    @lru_cache(maxsize=None)
    def rational_boundaries(self, denominator):
        return [denominator * midpoint for midpoint in self.midpoints]

    def nearest_rational(self, numerator, denominator=1):
        target = 2 * numerator
        boundaries = self.rational_boundaries(denominator)
        code = bisect_left(boundaries, target)
        if code < 126 and target == boundaries[code] and code & 1:
            code += 1
        return code

    def nearest_root(self, squared):
        target = 4 * squared
        code = bisect_left(self.square_midpoints, target)
        if code < 126 and target == self.square_midpoints[code] and code & 1:
            code += 1
        return code

    def word(self, x, operation):
        a, b = x >> 8, x & 255
        if a & 127 == 127 or b & 127 == 127:
            return 127
        ma, mb = self.magnitudes[a & 127], self.magnitudes[b & 127]
        sa, sb = a >> 7, b >> 7
        if operation == 'add':
            total = (-ma if sa else ma) + (-mb if sb else mb)
            sign = (total < 0) or (sa and sb)
            code = self.nearest_rational(abs(total))
        elif operation == 'multiply':
            sign = sa ^ sb
            code = self.nearest_rational(ma * mb, 1 << self.scale)
        elif operation == 'divide':
            sign = sa ^ sb
            if ma == 0:
                if mb == 0:
                    return 127
                code = 126
            else:
                code = self.nearest_rational(mb << self.scale, ma)
        elif operation == 'fmod':
            if ma == 0:
                return 127
            sign = sb
            code = self.nearest_rational(mb % ma)
        elif operation == 'hypot':
            sign = 0
            code = self.nearest_root(ma * ma + mb * mb)
        else:
            raise ValueError('unknown reference operation')
        return (int(sign) << 7) | code


def write_truth(path, words):
    mask = len(words) - 1
    path.write_text('\n'.join(''.join(str((words[mask ^ x] >> bit) & 1)
                                    for x in range(len(words)))
                              for bit in range(8)) + '\n')


class CompactFP8Test(unittest.TestCase):
    def test_adjacent_midpoint_identity_at_every_format_boundary(self):
        # Independently check the dyadic spacing law over every admitted code,
        # including the largest subnormal and all normal-binade transitions.
        for e, f in [(2, 5), (3, 4), (4, 3), (5, 2), (6, 1)]:
            ref = FiniteReference(e, f)
            for code in range(126):
                exponent = code >> f
                spacing = 1 << max(exponent - 1, 0)
                self.assertEqual(ref.magnitudes[code + 1] - ref.magnitudes[code], spacing)
                self.assertEqual(ref.magnitudes[code] + ref.magnitudes[code + 1],
                                 2 * ref.magnitudes[code] + spacing)

    def test_hypot_rounding_nan_and_sign_mutations_fail_complete_domain(self):
        for e, f in [(3, 4), (6, 1)]:
            ref = FiniteReference(e, f)
            words = [ref.word(x, 'hypot') for x in range(65536)]
            source = emit_finite_fp8('hypot', e, f, 'Hypot negative control')
            mutations = [
                source.replace('midpoint_square + trial[0]', 'midpoint_square'),
                source.replace("if ((a == 127) || (b == 127)) y = 8'h7f;",
                               "if (1'b0) y = 8'h7f;"),
                source.replace('y = lower_code;', 'y = {x[15], lower_code};'),
            ]
            with tempfile.TemporaryDirectory() as directory:
                truth, candidate = Path(directory) / 'input.truth', Path(directory) / 'candidate.v'
                write_truth(truth, words)
                for mutated in mutations:
                    self.assertNotEqual(mutated, source)
                    candidate.write_text(mutated)
                    result = verify(truth, candidate, default_yosys(), use_cache=False,
                                    frontend_timeout=120, compile_timeout=120, run_timeout=180,
                                    replay_workers=4)
                    self.assertEqual(result['frontend'], 'pass')
                    self.assertEqual(result['status'], 'mismatch', (e, f, result))

    def test_invalid_parameters_are_rejected(self):
        for e, f in [('4', 3), (4, '3'), (True, 6), (1, 6), (7, 0), (4, -1), (3, 3)]:
            with self.assertRaises(ValueError):
                emit_finite_fp8('add', e, f, 'invalid')
        with self.assertRaises(ValueError):
            emit_finite_fp8('lookup', 4, 3, 'invalid')

    def test_reference_signed_zero_nan_subnormal_carry_and_saturation(self):
        for e, f in [(2, 5), (3, 4), (4, 3), (5, 2), (6, 1)]:
            ref = FiniteReference(e, f)
            self.assertEqual(ref.nearest_rational(1, 2), 0)
            self.assertEqual(ref.nearest_rational(3, 2), 2)
            self.assertEqual(ref.nearest_rational(5, 2), 2)
            self.assertEqual(ref.nearest_rational(2 * (1 << f) - 1, 2), 1 << f)
            self.assertEqual(ref.nearest_rational(ref.magnitudes[126] * 4), 126)
            self.assertEqual(ref.word(0x8080, 'add'), 128)
            self.assertEqual(ref.word(0x8000, 'add'), 0)
            self.assertEqual(ref.word(0x8000, 'multiply'), 128)
            self.assertEqual(ref.word(0x0000, 'divide'), 127)
            self.assertEqual(ref.word(0x0001, 'divide'), 126)
            self.assertEqual(ref.word(0x0081, 'divide'), 254)
            self.assertEqual(ref.word(0x0081, 'fmod'), 127)
            self.assertEqual(ref.word(0x7f00, 'hypot'), 127)
            self.assertEqual(ref.word(0xff00, 'hypot'), 127)
            self.assertEqual(ref.word(0x8080, 'hypot'), 0)

    def test_general_formats_all_operations_complete_domain(self):
        # These formats are independent of the two benchmark formats.
        # Every generated truth file contains all 65536 input encodings.
        for e, f in [(3, 4), (6, 1)]:
            ref = FiniteReference(e, f)
            with tempfile.TemporaryDirectory() as directory:
                truth, candidate = Path(directory) / 'input.truth', Path(directory) / 'candidate.v'
                for operation in ['add', 'multiply', 'divide', 'fmod', 'hypot']:
                    words = [ref.word(x, operation) for x in range(65536)]
                    write_truth(truth, words)
                    candidate.write_text(emit_finite_fp8(operation, e, f, 'General format rational control'))
                    result = verify(truth, candidate, default_yosys(), use_cache=False,
                                    frontend_timeout=120, compile_timeout=120, run_timeout=180,
                                    replay_workers=4)
                    self.assertEqual(result['status'], 'pass', (e, f, operation, result))
                    self.assertEqual(result['vectors'], 65536)

    def test_wrong_orientation_and_wrong_signed_zero_are_detected(self):
        ref = FiniteReference(3, 4)
        with tempfile.TemporaryDirectory() as directory:
            truth, candidate = Path(directory) / 'input.truth', Path(directory) / 'candidate.v'
            words = [ref.word(x, 'divide') for x in range(65536)]
            source = emit_finite_fp8('divide', 3, 4, 'negative control')
            mutated = source.replace('(x[15] != x[7])', '(x[15] == x[7])')
            self.assertNotEqual(mutated, source)
            candidate.write_text(mutated)
            write_truth(truth, words)
            result = verify(truth, candidate, default_yosys(), use_cache=False,
                            frontend_timeout=120, compile_timeout=120, run_timeout=180,
                            replay_workers=4)
            self.assertEqual(result['status'], 'mismatch')
            candidate.write_text(source)
            write_truth(truth, list(reversed(words)))
            result = verify(truth, candidate, default_yosys(), use_cache=False,
                            frontend_timeout=120, compile_timeout=120, run_timeout=180,
                            replay_workers=4)
            self.assertEqual(result['status'], 'mismatch')


if __name__ == '__main__':
    unittest.main()

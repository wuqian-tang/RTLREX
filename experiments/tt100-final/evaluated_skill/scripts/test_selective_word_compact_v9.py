#!/usr/bin/env python3
"""Exercise visible single-use operators at their signed-width boundaries."""
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from truth.fixed_point_compact import compact_fixed_point_operators
from cost.RTL_cost_calculator import evaluate_rtl
from verify.truth_yosys import default_yosys, verify


def write_words(path, n, width, words):
    mask = (1 << n) - 1
    path.write_text('\n'.join(''.join(str((words[x ^ mask] >> bit) & 1)
                                     for x in range(1 << n))
                             for bit in range(width)) + '\n')


class SelectiveWordTests(unittest.TestCase):
    def test_visible_single_use_and_shared_repeated_operator(self):
        raw = '''module top;
  always @(*) begin
    a = b + c;
    d = a + c;
    y = (a * d) >>> 5;
  end
endmodule
'''
        old = compact_fixed_point_operators(raw)
        new = compact_fixed_point_operators(raw, min_word_operator_uses=2)
        self.assertIn('function signed [63:0] fp_add;', new)
        self.assertNotIn('fp_mul', new)
        self.assertNotIn('fp_asr', new)
        self.assertIn('(a * d)', new)
        self.assertIn('>>> 5', new)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'candidate.v'
            path.write_text(old)
            before = evaluate_rtl(str(path))[0]
            path.write_text(new)
            after = evaluate_rtl(str(path))[0]
        self.assertLess(after, before)

    def test_signed64_complete_boundary_matrix_and_negative_control(self):
        values = [-(1 << 63), -(1 << 63) + 1, -(1 << 62),
                  -129, -65, -7, -1, 0, 1, 7, 65, 129,
                  (1 << 62) - 1, 1 << 62, (1 << 63) - 2, (1 << 63) - 1]
        def literal(value):
            if value == -(1 << 63):
                return "64'sh8000000000000000"
            return ('-' if value < 0 else '') + "64'sd" + str(abs(value))
        def wrap(value):
            value &= (1 << 64) - 1
            return value - (1 << 64) if value >= 1 << 63 else value
        def division(value):
            return (-1 if value < 0 else 1) * (abs(value) // 7)
        words = []
        for x in range(256):
            a, b = values[x & 15], values[x >> 4]
            words.append(wrap(division(wrap(a * b)) + (a >> 5) +
                              (wrap(a << 3) if a < b else wrap(a - b))) & ((1 << 64) - 1))
        first = '\n'.join(f"    {'if' if i == 0 else 'else if'} (x[3:0] == 4'd{i}) a = {literal(value)};"
                          for i, value in enumerate(values[:-1]))
        first += f'\n    else a = {literal(values[-1])};'
        second = '\n'.join(f"    {'if' if i == 0 else 'else if'} (x[7:4] == 4'd{i}) b = {literal(value)};"
                           for i, value in enumerate(values[:-1]))
        second += f'\n    else b = {literal(values[-1])};'
        raw = f'''module top(input [7:0] x, output reg [63:0] y);
  reg signed [63:0] a, b, result;
  always @(*) begin
{first}
{second}
    result = ((a * b) / 64'sd7) + (a >>> 64'sd5) + ((a < b) ? (a <<< 64'sd3) : (a - b));
    y = result;
  end
endmodule
'''
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            truth = base / 'boundaries.truth'
            rtl = base / 'boundaries.v'
            write_words(truth, 8, 64, words)
            for minimum in (1, 2):
                source = compact_fixed_point_operators(raw,
                    body_start='    result =', min_word_operator_uses=minimum)
                rtl.write_text(source)
                proof = verify(truth, rtl, default_yosys(), use_cache=False,
                               frontend_timeout=120, compile_timeout=120,
                               run_timeout=180)
                self.assertEqual(proof['status'], 'pass', proof)
                self.assertEqual(proof['vectors'], 256)
            rtl.write_text(source.replace('>>>', '>>'))
            proof = verify(truth, rtl, default_yosys(), use_cache=False,
                           frontend_timeout=120, compile_timeout=120,
                           run_timeout=180)
            self.assertNotEqual(proof['status'], 'pass', proof)

    def test_invalid_minimum_rejected(self):
        with self.assertRaises(ValueError):
            compact_fixed_point_operators('module top; endmodule',
                                         min_word_operator_uses=0)


if __name__ == '__main__':
    unittest.main()

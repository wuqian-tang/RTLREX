#!/usr/bin/env python3
"""Independent numerical, full-domain, boundary and fail-closed controls."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from truth.dynamic_round_compact_v8 import RNE64_HELPER, share_dynamic_round_to_even
from verify.truth_yosys import verify

ROOT = Path(__file__).resolve().parents[5]
YOSYS = Path(os.environ.get('YOSYS', str(ROOT / 'external/yosys/yosys')))


def kernel(a=3, b=5, width=8):
    return f'''module top(input [{width-1}:0] x, output reg [63:0] y);
  reg signed [63:0] value, rounded, rem, half_round;
  integer shift;
  always @(*) begin
    value = $signed(x); rounded = 0; rem = 0; half_round = 0; shift = 0;
    if (x[0]) begin shift = {a}; end else begin shift = {b}; end
    rounded = value >>> shift;
    rem = value - (rounded <<< shift);
    half_round = 64'sd1 <<< (shift - 1);
    if ((rem > half_round) || ((rem == half_round) && rounded[0]))
      rounded = rounded + 1;
    y = rounded;
  end
endmodule
'''


def rne(value, shift):
    quotient, remainder = divmod(value, 1 << shift)
    half = 1 << (shift-1)
    return quotient + int(remainder > half or (remainder == half and quotient & 1))


class DynamicRoundTests(unittest.TestCase):
    def prove_words(self, source, words):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            rtl = base / 'top.v'; rtl.write_text(source)
            truth = base / 'input.truth'
            truth.write_text('\n'.join(''.join(str((words[x ^ 255] >> bit) & 1)
                                                   for x in range(256))
                                       for bit in range(64))+'\n')
            result = verify(truth, rtl, YOSYS, use_cache=False,
                            frontend_timeout=120, compile_timeout=120, run_timeout=180)
            self.assertEqual(result['status'], 'pass', result)

    def test_generic_nonbenchmark_full_domains(self):
        for a, b in ((2, 6), (1, 63), (4, 7)):
            source = kernel(a, b)
            changed = share_dynamic_round_to_even(source)
            self.assertNotEqual(source, changed)
            words = [rne(x if x < 128 else x-256, a if x & 1 else b) & ((1 << 64)-1)
                     for x in range(256)]
            self.prove_words(changed, words)

    def test_canonical_helper_reuse(self):
        source = kernel().replace('  always @(*) begin', RNE64_HELPER+'  always @(*) begin')
        changed = share_dynamic_round_to_even(source)
        self.assertNotEqual(source, changed)
        self.assertEqual(changed.count('function signed [63:0] semantic_rne64;'), 1)

    def test_two_rounding_stages_remain_separate(self):
        source = kernel()
        block = source[source.index('    if (x[0])'):source.index('    y = rounded;')]
        source = source.replace('    y = rounded;', '    value = rounded;\n'+block+'    y = rounded;')
        changed = share_dynamic_round_to_even(source)
        self.assertEqual(changed.count('rounded = semantic_rne64('), 2)
        self.assertIn('value = rounded;', changed)
        words = []
        for x in range(256):
            value, shift = (x if x < 128 else x-256), (3 if x & 1 else 5)
            words.append(rne(rne(value, shift), shift) & ((1 << 64)-1))
        self.prove_words(changed, words)

    def test_idempotent_and_all_branch_constants(self):
        for shift in range(1, 64):
            source = kernel(shift, 64-shift)
            changed = share_dynamic_round_to_even(source)
            self.assertNotEqual(source, changed)
            self.assertEqual(share_dynamic_round_to_even(changed), changed)

    def test_shift_definition_negative_controls(self):
        original = kernel()
        variants = [kernel(0, 3), kernel(3, 64),
                    original.replace(' else begin shift = 5; end', ''),
                    original.replace('shift = 3;', 'shift = x;'),
                    original.replace('shift = 3;', 'if (x[1]) shift = 3;'),
                    original.replace('shift = 3;', 'shift = 3; shift = 4;'),
                    original.replace('shift = 3;', 'shift = 3; rem = x;'),
                    original.replace('shift = 3;', 'shift = 3; value = half_round;'),
                    original.replace('shift = 3;', 'shift = 3; value = user_function(x);'),
                    original.replace('integer shift;', 'integer shift; wire extra = shift;'),
                    original.replace('    rounded = value >>> shift;', '    shift = 0;\n    rounded = value >>> shift;')]
        for source in variants:
            self.assertEqual(share_dynamic_round_to_even(source), source)

    def test_extra_scratch_uses_and_unknown_syntax_fail_closed(self):
        original = kernel()
        variants = [original.replace('y = rounded;', 'y = rounded + rem;'),
                    original.replace('y = rounded;', 'y = rounded + half_round;'),
                    original.replace('y = rounded;', 'rem = rem + 1; y = rounded;'),
                    original.replace('y = rounded;', 'if (x[0]) y = rem; else y = rounded;'),
                    original.replace('y = rounded;', 'repeat (2) y = rounded;'),
                    original.replace('rem = value -', 'rem = value +'),
                    original.replace('rounded = rounded + 1;', 'rounded = rounded + 1; else rounded = 0;'),
                    original.replace('half_round = 64', '// matched comment\n    half_round = 64')]
        for source in variants:
            self.assertEqual(share_dynamic_round_to_even(source), source)

    def test_types_aliases_and_unknown_helper_fail_closed(self):
        original = kernel()
        variants = [original.replace('reg signed [63:0]', 'reg [63:0]'),
                    original.replace('integer shift;', 'reg [5:0] shift;'),
                    original.replace('value >>> shift', 'rounded >>> shift'),
                    original.replace('  always @(*) begin', RNE64_HELPER.replace('[64:0]', '[63:0]')+'  always @(*) begin'),
                    original.replace('endmodule', 'endmodule\nunknown'),
                    original.replace('y = rounded;', 'y = rounded; `bad'),
                    original.replace('y = rounded;', 'y = rounded; /* unknown */')]
        for source in variants:
            self.assertEqual(share_dynamic_round_to_even(source), source)

    def test_signed64_boundary_and_all_shift_pairs(self):
        if not shutil.which('iverilog'):
            self.skipTest('Icarus unavailable')
        values = {-(1 << 63), -(1 << 63)+1, -1, 0, 1, (1 << 63)-2, (1 << 63)-1}
        for shift in range(1, 64):
            half = 1 << (shift-1)
            for center in (-3*(1 << shift), -half, half, 3*(1 << shift)):
                values.update(v for v in (center-1, center, center+1) if -(1 << 63) <= v < 1 << 63)
        # Directly compare the original signed-64 procedural operations and
        # helper, including wrapped 64-bit subtraction and increment semantics.
        lines = ['module test;', RNE64_HELPER,
                 'reg signed [63:0] value, rounded, rem, half_round, actual;',
                 'integer shift;', 'initial begin']
        expected = []
        for value in sorted(values):
            for shift in range(1, 64):
                raw = value & ((1 << 64)-1)
                lines += [f"value = 64'h{raw:016x}; shift = {shift};",
                          'rounded = value >>> shift;',
                          'rem = value - (rounded <<< shift);',
                          "half_round = 64'sd1 <<< (shift - 1);",
                          'if ((rem > half_round) || ((rem == half_round) && rounded[0])) rounded = rounded + 1;',
                          "actual = semantic_rne64(value, shift, half_round - 65'sd1);",
                          'if (actual !== rounded) $fatal(1, "reference mismatch");',
                          '$display("%h", actual);']
                expected.append(rne(value, shift) & ((1 << 64)-1))
        lines += ['$finish; end', 'endmodule']
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, executable = base/'test.v', base/'test.vvp'
            source.write_text('\n'.join(lines))
            run = subprocess.run(['iverilog', '-o', str(executable), str(source)], text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            run = subprocess.run(['vvp', str(executable)], text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual([int(line, 16) for line in run.stdout.splitlines()], expected)


if __name__ == '__main__':
    unittest.main()

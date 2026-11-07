"""Independent complete-domain and counterexample controls for bounded roots."""
import math
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from truth.integer_root_compact import (emit_bounded_integer_sqrt,
    emit_descending_integer_sqrt, choose_integer_sqrt)
from verify.truth_yosys import default_yosys, verify


class BoundedRootTests(unittest.TestCase):
    def proof(self, width, source):
        outputs = (width+1)//2
        words = [math.isqrt(value) for value in range(1 << width)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            truth, rtl = directory / 'input.truth', directory / 'candidate.v'
            mask = (1 << width)-1
            truth.write_text('\n'.join(''.join(str((words[value ^ mask] >> bit) & 1)
                                               for value in range(1 << width))
                                       for bit in range(outputs))+'\n')
            rtl.write_text(source)
            return verify(truth, rtl, default_yosys(), use_cache=False)

    def test_complete_nonbenchmark_domains(self):
        for width in (1, 3, 5, 7):
            result = self.proof(width, emit_bounded_integer_sqrt(width, (width+1)//2))
            self.assertEqual(result['frontend'], 'pass', result)
            self.assertEqual(result['status'], 'pass', result)
            self.assertEqual(result['vectors'], 1 << width)

    def test_wrong_perfect_square_boundary_is_rejected(self):
        original = emit_bounded_integer_sqrt(7, 4)
        mutated = original.replace('squared <= x', 'squared < x')
        self.assertNotEqual(original, mutated)
        result = self.proof(7, mutated)
        self.assertEqual(result['frontend'], 'pass', result)
        self.assertEqual(result['status'], 'mismatch', result)

    def test_width_resource_contract(self):
        for width, output in ((0, 0), (17, 9), (8, 3), (16, 9), (1.5, 1), (True, 1)):
            with self.assertRaises(ValueError):
                emit_bounded_integer_sqrt(width, output)
            with self.assertRaises(ValueError):
                emit_descending_integer_sqrt(width, output)

    def test_descending_complete_even_and_odd_domains(self):
        for width in (1, 2, 3, 5, 6, 7, 9, 15):
            source = emit_descending_integer_sqrt(width, (width+1)//2)
            result = self.proof(width, source)
            self.assertEqual(result['frontend'], 'pass', result)
            self.assertEqual(result['status'], 'pass', result)
            self.assertEqual(result['vectors'], 1 << width)

    def test_descending_short_search_and_square_truncation_are_rejected(self):
        source = emit_descending_integer_sqrt(5, 3)
        for changed in (source.replace('repeat (7)', 'repeat (6)'),
                        source.replace('wire [5:0] radicand', 'wire [4:0] radicand'),
                        source.replace('y * y > radicand', 'y * y >= radicand')):
            self.assertNotEqual(changed, source)
            result = self.proof(5, changed)
            self.assertEqual(result['frontend'], 'pass', result)
            self.assertEqual(result['status'], 'mismatch', result)

    def test_active_price_and_resource_bounds(self):
        import csv
        from cost.RTL_cost_calculator import set_operator_cost_csv
        profile = HERE / 'cost/syntax_cost.csv'
        prefix = '''module top(input [5:0] x, output reg [2:0] y);
  integer index;
  always @(*) begin
    y=0; index=2;
    repeat(3) begin
      y[index]=1'b1; y[index]=y*y<=x; index=index-1;
    end
  end
endmodule
'''
        set_operator_cost_csv(str(profile))
        scan = choose_integer_sqrt(6, 3, prefix)
        self.assertEqual(scan, emit_descending_integer_sqrt(6, 3))
        self.assertEqual(choose_integer_sqrt(17, 9, prefix), prefix)
        self.assertEqual(choose_integer_sqrt(6, 2, prefix), prefix)
        with tempfile.TemporaryDirectory() as temporary:
            modified = Path(temporary) / 'price.csv'
            with profile.open(newline='') as stream:
                reader = csv.DictReader(stream)
                rows, fields = list(reader), reader.fieldnames
            for row in rows:
                if row['key'] in ('+', '-', '>', '?:'):
                    row['cost'] = '100'
            with modified.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            try:
                set_operator_cost_csv(str(modified))
                self.assertEqual(choose_integer_sqrt(6, 3, prefix), prefix)
            finally:
                set_operator_cost_csv(str(profile))
        for source in (prefix, scan):
            result = self.proof(6, source)
            self.assertEqual(result['status'], 'pass', result)


if __name__ == '__main__':
    unittest.main()

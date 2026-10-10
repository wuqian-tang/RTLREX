"""Cost must retain the operators of expressions inside concatenations."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cost.RTL_cost_calculator import evaluate_rtl, operator_cost


class ConcatExpressionCostTests(unittest.TestCase):
    def score(self, expression):
        source = ('module top(input [7:0] a, b, input c, output [7:0] y); '
                  'assign y = ' + expression + '; endmodule\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.v'
            path.write_text(source)
            return evaluate_rtl(str(path))[::2]

    def test_single_item_wrapper_preserves_each_operator(self):
        expressions = [
            'a + b', '(a / (b + 1)) % 8', 'c ? (a - b) : (a >> 1)',
            'a[3:0] ^ b[3:0]', 'c && (a == b)', '!(|a)', '~a',
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                bare, bare_detail = self.score(expression)
                wrapped, wrapped_detail = self.score('{' + expression + '}')
                self.assertEqual(wrapped, bare + operator_cost('concat'))
                wrapped_detail.pop('concat')
                self.assertEqual(wrapped_detail, bare_detail)

    def test_multiple_items_include_selected_and_nested_operations(self):
        cost, detail = self.score('{a[7:4] + b[7:4], a[3:0] ^ b[3:0]}')
        self.assertEqual(detail['+'], operator_cost('+'))
        self.assertEqual(detail['^'], 4 * operator_cost('^'))
        self.assertEqual(detail['select'], 4 * operator_cost('select'))
        self.assertEqual(detail['concat'], 2 * operator_cost('concat'))
        self.assertEqual(cost, sum(detail.values()))

    def test_deep_wrappers_cannot_hide_computation(self):
        bare, detail = self.score('a * b + a')
        wrapped, wrapped_detail = self.score('{' * 12 + 'a * b + a' + '}' * 12)
        self.assertEqual(wrapped, bare + 12 * operator_cost('concat'))
        self.assertEqual(wrapped_detail['*'], detail['*'])
        self.assertEqual(wrapped_detail['+'], detail['+'])

    def test_replication_expression_retains_body(self):
        _, detail = self.score('{2{a[3:0] ^ b[3:0]}}')
        self.assertEqual(detail['^'], 4 * operator_cost('^'))
        self.assertEqual(detail['select'], 2 * operator_cost('select'))
        self.assertGreater(detail['concat'], 0)

    def test_unwrapped_expression_unchanged(self):
        _, detail = self.score('a + b')
        self.assertEqual(detail, {'+': operator_cost('+')})


if __name__ == '__main__':
    unittest.main()

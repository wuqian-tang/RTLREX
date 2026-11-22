"""Direct selected-width controls; not a complete Verilog type evaluator."""
import sys
sys.dont_write_bytecode=True
import importlib.util
import tempfile
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parent/'cost/RTL_cost_calculator.py'
spec=importlib.util.spec_from_file_location('new_cost_selected_width',SOURCE)
calculator=importlib.util.module_from_spec(spec);sys.modules[spec.name]=calculator;spec.loader.exec_module(calculator)

class SelectedWidthControls(unittest.TestCase):
    def width(self, declaration, expression, side='right'):
        tokens=calculator.tokenize(expression)
        widths=calculator.parse_decl_widths(declaration)
        index=tokens.index('^')
        return (calculator.operand_width_right if side=='right' else calculator.operand_width_left)(tokens,[False]*len(tokens),index,widths)

    def test_selected_bit_and_constant_slice(self):
        self.assertEqual(self.width('wire [1339:0] m;','a ^ m[4]'),1)
        self.assertEqual(self.width('wire [1339:0] m;','a ^ m[15:8]'),8)
        self.assertEqual(self.width('wire [1339:0] m;','m[15:8] ^ a','left'),8)

    def test_plain_packed_bus_unchanged(self):
        self.assertEqual(self.width('wire [1339:0] m;','a ^ m'),1340)

    def test_indexed_partselect(self):
        self.assertEqual(self.width('wire [15:0] m;','a ^ m[index +: 4]'),4)
        self.assertEqual(self.width('wire [15:0] m;','a ^ m[index -: 3]'),3)

    def test_word_array_element_is_word(self):
        declaration='reg [7:0] word_array [0:3];'
        self.assertEqual(self.width(declaration,'a ^ word_array[index]'),8)
        self.assertEqual(self.width(declaration,'word_array[index] ^ a','left'),8)
        self.assertEqual(self.width(declaration,'a ^ word_array[index][2]'),1)
        self.assertEqual(self.width(declaration,'a ^ word_array[index][7:4]'),4)

    def test_nested_array_index(self):
        self.assertEqual(self.width('reg [7:0] word_array [0:3];','a ^ word_array[indices[0]]'),8)

    def test_two_unpacked_dimensions(self):
        d='reg [10:0] grid [0:3][0:2];'
        self.assertEqual(self.width(d,'a ^ grid[i][j]'),11)
        with self.assertRaisesRegex(ValueError,'unindexed unpacked'):
            self.width(d,'a ^ grid[i]')

    def test_multidimensional_packed_select(self):
        d='wire [1:0][7:0] words;'
        self.assertEqual(self.width(d,'a ^ words[i]'),8)
        self.assertEqual(self.width(d,'a ^ words[i][j]'),1)
        self.assertEqual(self.width(d,'a ^ words[0:0]'),8)
        self.assertEqual(self.width(d,'a ^ words[1:0]'),16)

    def test_ansi_declarator_shapes(self):
        widths=calculator.parse_decl_widths('module top(input [15:0] x, output [7:0] y); wire [7:0] z; endmodule')
        self.assertEqual((widths['x'],widths['y'],widths['z']),(16,8,8))
        self.assertEqual(self.width('module top(input [15:0] x, output [7:0] words [0:3]);','a ^ words[i]'),8)

    def test_initializer_comma_not_declaration(self):
        d="wire [7:0] mr={1'b0,n[14:8]}+r, other={x[0],n[6:0]};"
        widths=calculator.parse_decl_widths(d)
        self.assertEqual(set(widths),{'mr','other'})
        self.assertEqual(self.width(d,'a ^ other[3]'),1)

    def test_integer_array_width(self):
        self.assertEqual(self.width('integer word_array[0:3];','a ^ word_array[i]'),32)

    def test_ansi_integer_effective_type(self):
        d='module top(input integer incoming, output int outgoing, output byte small); endmodule'
        widths=calculator.parse_decl_widths(d)
        self.assertEqual((widths['incoming'],widths['outgoing'],widths['small']),(32,32,8))
        self.assertEqual(self.width(d,'a ^ outgoing[15:8]'),8)

    def test_unknown_declared_type_selected_operand_rejected(self):
        with self.assertRaisesRegex(ValueError,'undeclared or unsupported type'):
            self.width('word_t value;','a ^ value[0]')

    def test_unknown_selected_word_and_array_slice_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'unknown packed'):
            self.width('reg [W-1:0] word_array [0:3];','a ^ word_array[i]')
        with self.assertRaisesRegex(ValueError,'unpacked array slice'):
            self.width('reg [7:0] word_array [0:3];','a ^ word_array[1:0]')
        with self.assertRaisesRegex(ValueError,'supported constant'):
            self.width('wire [15:0] m;','a ^ m[hi:lo]')

    def test_small_complete_cost_controls(self):
        examples=[
          ('wire [1339:0] m; assign y=m[0]^m[1];', {'^':3,'select':2}),
          ('reg [7:0] words [0:3]; assign y=words[0]^words[1];', {'^':24,'select':2}),
          ('reg [1:0][7:0] words; assign y=words[0]^words[1];', {'^':24,'select':2}),
          ('wire [15:0] m; assign y=m[base+:4]^m[base-:4];', {'^':12,'select':2,'+':1,'-':1}),
        ]
        with tempfile.TemporaryDirectory() as d:
            for i,(body,expected) in enumerate(examples):
                p=Path(d)/f'control{i}.v';p.write_text('module top(input a,output y);\n'+body+'\nendmodule\n')
                cost,_,detail=calculator.evaluate_rtl(str(p))
                self.assertEqual(detail,expected);self.assertEqual(cost,sum(expected.values()))

if __name__=='__main__':unittest.main()

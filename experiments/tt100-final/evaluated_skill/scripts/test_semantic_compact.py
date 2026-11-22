#!/usr/bin/env python3
"""Width and complete-domain controls for semantic source factoring."""
from pathlib import Path
from fractions import Fraction
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from truth.semantic_compact import (share_input_fields, share_round_to_even,
    emit_binary_square, emit_binary_reciprocal, emit_binary_sqrt,
    emit_binary_recip_power, emit_binary_root)
from truth.semantic_compact import linearize_float_pack, share_signed_operators, compact_semantic_rtl
from verify.truth_yosys import default_yosys, verify


class SemanticCompactionTests(unittest.TestCase):
    def test_static_fields_exact_complete_domain(self):
        n, m = 8, 8
        source = '''module top(input [7:0] x, output [7:0] y);
  assign y = (x[7:4] * x[7:4]) + x[3:0] + x[3:0];
endmodule
'''
        changed = share_input_fields(source)
        self.assertEqual(changed.count('x[7:4]'), 1)
        self.assertEqual(changed.count('x[3:0]'), 0)
        self.assertIn('wire [3:0] input_field_7_4', changed)
        words = [(((x >> 4) ** 2) + 2 * (x & 15)) & 255 for x in range(256)]
        self.prove(n, m, words, changed)

    def test_signed_ports_and_macros_unchanged(self):
        source = 'module top(input signed [7:0] x, output [7:0] y); assign y=x[3:0]+x[3:0]; endmodule'
        self.assertEqual(share_input_fields(source), source)
        source='''module top(input [7:0] x, output [7:0] y);
  function [7:0] f;
    input [7:0] x;
    begin f=x[3:0]+x[3:0]; end
  endfunction
  assign y=x[3:0]+f(x);
endmodule
'''
        self.assertEqual(share_input_fields(source),source)

    def test_mixed_wide_unsigned_arithmetic_not_compacted_as_signed64(self):
        source='''module top(input [7:0] x, output reg [7:0] y);
  reg [127:0] wide;
  reg signed [63:0] scalar;
  always @(*) begin
    wide = 128'd18446744073709551616 + x;
    scalar = x;
    y = (wide >> 64) + scalar;
  end
endmodule
'''
        changed=compact_semantic_rtl(source)
        self.assertNotIn('fp_add',changed)
        self.assertNotIn('fp_shr',changed)
        self.prove(8,8,[(x+1)&255 for x in range(256)],changed)
        signed_source=source.replace('reg [127:0] wide;', 'reg signed [127:0] wide;')
        signed_changed=compact_semantic_rtl(signed_source)
        self.assertNotIn('fp_add',signed_changed)
        self.assertNotIn('fp_shr',signed_changed)
        self.prove(8,8,[(x+1)&255 for x in range(256)],signed_changed)
        source = 'module top(input [7:0] x, output [7:0] y); `define A x[3:0]+x[3:0]\n endmodule'
        self.assertEqual(share_input_fields(source), source)

    @staticmethod
    def kernel() -> str:
        return '''module top(input [7:0] x, output reg [15:0] y);
  reg signed [63:0] source, first, rounded, rem;
  always @(*) begin
    source = $signed(x); first=0; rounded=0; rem=0;
    first = source >>> 3;
    rem = source - (first <<< 3);
    if ((rem > 64'sd4) || ((rem == 64'sd4) && first[0]))
      first = first + 1;
    rounded = first >>> 1;
    rem = first - (rounded <<< 1);
    if ((rem > 64'sd1) || ((rem == 64'sd1) && rounded[0]))
      rounded = rounded + 1;
    y = rounded;
  end
endmodule
'''

    def test_rounding_signed_complete_domain(self):
        source = self.kernel()
        changed = share_round_to_even(source)
        self.assertEqual(changed.count('semantic_rne64('), 2)
        self.assertIn('reg signed [64:0] extended', changed)
        def rnd(value, shift):
            quotient = value >> shift
            remainder = value - (quotient << shift)
            half = 1 << (shift - 1)
            return quotient + int(remainder > half or (remainder == half and quotient & 1))
        words = [rnd(rnd(x if x < 128 else x - 256, 3), 1) & 65535 for x in range(256)]
        self.prove(8, 16, words, changed)

    def test_rounding_fail_closed_if_remainder_read(self):
        source = self.kernel().replace('y = rounded;', 'y = rounded + rem;')
        self.assertEqual(share_round_to_even(source), source)

    def test_rounding_aliases_and_read_modify_write_are_not_factored(self):
        source = self.kernel().replace('first = source >>> 3;', 'source = source >>> 3;').replace(
            'rem = source - (first <<< 3);', 'rem = source - (source <<< 3);').replace(
            'first[0]', 'source[0]').replace('first = first + 1;', 'source = source + 1;')
        self.assertEqual(share_round_to_even(source), source)
        source = self.kernel().replace('y = rounded;', 'rem = rem + 1; y = rounded;')
        self.assertEqual(share_round_to_even(source), source)

    def test_integer_width_cleanup_signed_extension_and_root_truncation(self):
        from reverse import truth_reverse as reverse
        for n, m, signed in ((4, 4, False), (6, 3, False), (6, 9, False),
                             (4, 4, True), (6, 3, True), (6, 9, True)):
            half, mask = n//2, (1<<m)-1
            def sign(v):
                return v-(1<<half) if signed and v >= 1<<(half-1) else v
            words=[sign(x % (1<<half))*sign(x>>half) & mask for x in range(1<<n)]
            candidate=(reverse.try_signed_mul if signed else reverse.try_unsigned_mul)(n,m,words)
            self.assertIsNotNone(candidate)
            self.prove(n,m,words,candidate.verilog)
        for n, m in ((6,3),(6,8)):
            half, mask = n//2,(1<<m)-1
            words=[(x % (1<<half)) // (x>>half) if x>>half else mask for x in range(1<<n)]
            self.prove(n,m,words,reverse.try_unsigned_div(n,m,words).verilog)
        import math
        for n, m in ((6,2),(8,4),(5,2),(7,6),(5,3)):
            words=[math.isqrt(x) % (1<<m) for x in range(1<<n)]
            self.prove(n,m,words,reverse.try_isqrt(n,m,words).verilog)

    def test_signed64_boundary_vectors(self):
        if not shutil.which('iverilog'):
            self.skipTest('Icarus unavailable')
        transformed = share_round_to_even(self.kernel())
        helper = transformed.split('  // Exact signed')[1].split('  always')[0]
        helper = '  // Exact signed' + helper
        values = [-(1 << 63), -(1 << 63) + 1, -(1 << 63) + 7,
                  -9, -8, -7, -3, -1, 0, 1, 3, 7, 8, 9,
                  (1 << 63) - 9, (1 << 63) - 2, (1 << 63) - 1]
        lines = ['module test;', helper, 'initial begin']
        expected = []
        for value in values:
            for shift in (1, 2, 3, 17, 32, 62, 63):
                raw = value & ((1 << 64) - 1)
                lines.append(f"$display(\"%h\", semantic_rne64(64'h{raw:016x},6'd{shift},65'sd{(1 << (shift-1))-1}));")
                quotient = value >> shift
                remainder = value - (quotient << shift)
                half = 1 << (shift - 1)
                expected.append((quotient + int(remainder > half or (remainder == half and quotient & 1))) & ((1 << 64) - 1))
        lines += ['$finish; end', 'endmodule']
        with tempfile.TemporaryDirectory() as directory:
            src, executable = Path(directory) / 'test.v', Path(directory) / 'test.vvp'
            src.write_text('\n'.join(lines))
            compile_result = subprocess.run(['iverilog', '-o', str(executable), str(src)], capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run = subprocess.run(['vvp', str(executable)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual([int(line, 16) for line in run.stdout.splitlines()], expected)

    def test_binary_formats_exact_oracle(self):
        """Oracle enumerates representable values, independent of emitters."""
        for exponent_width, fraction_width in ((3, 2), (3, 3), (4, 2)):
            width = 1 + exponent_width + fraction_width
            maximum = (1 << exponent_width) - 1
            bias = (1 << (exponent_width - 1)) - 1
            infinity = maximum << fraction_width
            nan = infinity | (1 << (fraction_width - 1))
            def power(exponent):
                return Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)
            def value(code):
                e, f = code >> fraction_width, code % (1 << fraction_width)
                if e == 0:
                    return Fraction(f) * power(1 - bias - fraction_width)
                return Fraction((1 << fraction_width) + f) * power(e - bias - fraction_width)
            # Infinity is represented by the next overflowing finite endpoint
            # for rounding; all codes above it are canonical exceptional data.
            values = [(code, value(code)) for code in range(infinity + 1)]
            def nearest(v, root_degree=1):
                for (low, lo), (high, hi) in zip(values, values[1:]):
                    midpoint = (lo + hi) / 2
                    threshold = midpoint ** root_degree
                    if v < threshold or (v == threshold and not low & 1):
                        return low if low >= 1 << fraction_width else 0
                return infinity
            for kind, emitter in [('square', emit_binary_square), ('reciprocal', emit_binary_reciprocal), ('sqrt', emit_binary_sqrt),
                                  ('recip_square', lambda e, f, d: emit_binary_recip_power(e, f, 2, d)),
                                  ('recip_cube', lambda e, f, d: emit_binary_recip_power(e, f, 3, d)),
                                  ('cbrt', lambda e, f, d: emit_binary_root(e, f, 3, False, d)),
                                  ('recip_sqrt', lambda e, f, d: emit_binary_root(e, f, 2, True, d)),
                                  ('recip_cbrt', lambda e, f, d: emit_binary_root(e, f, 3, True, d))]:
                words = []
                for x in range(1 << width):
                    sign = x >> (width - 1)
                    code = x % (1 << (width - 1))
                    e, f = code >> fraction_width, code % (1 << fraction_width)
                    signed_zero = sign << (width - 1)
                    reciprocal = kind.startswith('recip')
                    signed_reciprocal = kind in ('reciprocal', 'recip_cube', 'recip_sqrt', 'recip_cbrt')
                    odd_root = kind in ('cbrt', 'recip_cbrt')
                    square_root = kind in ('sqrt', 'recip_sqrt')
                    if e == maximum:
                        y = nan if f or (square_root and sign) else (0 if reciprocal else infinity)
                        if signed_reciprocal and not f and not (square_root and sign):
                            y = signed_zero
                        if odd_root and not reciprocal and not f:
                            y += signed_zero
                    elif e == 0:
                        y = 0 if kind == 'square' else signed_zero if not reciprocal else (signed_zero if signed_reciprocal else 0) + infinity
                    elif square_root and sign:
                        y = nan
                    else:
                        v = value(code)
                        if kind == 'square':
                            y = nearest(v*v)
                        elif kind in ('reciprocal', 'recip_square', 'recip_cube'):
                            y = nearest(1 / v**(1 if kind == 'reciprocal' else 2 if kind == 'recip_square' else 3))
                        else:
                            y = nearest(1/v if reciprocal else v, root_degree=2 if square_root else 3)
                        if signed_reciprocal or odd_root:
                            y += signed_zero
                    words.append(y)
                self.prove(width, width, words, emitter(exponent_width, fraction_width, kind))

    def test_double_round_linear_pack_boundaries(self):
        """Both normal and exponent-zero promotion use original two stages."""
        for f, e, bias in ((7, 8, 127), (10, 5, 15)):
            normal_shift = 23-f
            sub_shift = normal_shift+1
            source = f'''module top(input [11:0] x, output reg [15:0] y);
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded;
  always @(*) begin
    bin_exp = $signed({{1'b0, x[11:10]}}) - {bias+1};
    rounded32 = 16769032 + x[9:0] * 8;
    rounded=0; out_exp=0;
    if (rounded32 >= 16777216) begin
      rounded32 = 8388608;
      bin_exp = bin_exp + 1;
    end
    out_exp = bin_exp + {bias};
    if (out_exp < 0) y=0;
    else if (out_exp == 0) begin
      rounded = rounded32 >>> {sub_shift};
      rounded = (rounded32 + {((1 << (sub_shift-1))-1)} + rounded[0]) >>> {sub_shift};
      y = rounded >= {1<<f} ? {1<<f} : 0;
    end else begin
      rounded = rounded32 >>> {normal_shift};
      rounded = (rounded32 + {((1 << (normal_shift-1))-1)} + rounded[0]) >>> {normal_shift};
      if (rounded >= {2<<f}) begin
        rounded = {1<<f};
        out_exp = out_exp + 1;
      end
      if (out_exp >= {(1<<e)-1}) y = {((1<<e)-1)<<f};
      else y = {{out_exp[{e-1}:0], rounded[{f-1}:0]}};
    end
  end
endmodule
'''
            changed = linearize_float_pack(source)
            self.assertNotEqual(changed, source)
            self.assertNotIn('rounded32 >= 16777216', changed)
            self.assertIn(f'out_exp = (out_exp - 1) * {1<<f} + rounded;', changed)
            words=[]
            def rnd(v, shift):
                q=v >> shift; r=v-(q<<shift); h=1 << (shift-1)
                return q+int(r>h or r==h and q&1)
            for x in range(4096):
                exponent = (x>>10)-1
                value = 16769032 + (x&1023)*8
                if value >= 16777216:
                    value = 8388608; exponent += 1
                if exponent < 0:
                    y=0
                elif exponent == 0:
                    y=(1<<f) if rnd(value,sub_shift) >= 1<<f else 0
                else:
                    q=rnd(value,normal_shift)
                    if q>=2<<f:
                        q=1<<f; exponent+=1
                    y=((1<<e)-1)<<f if exponent >= (1<<e)-1 else (exponent<<f)+(q % (1<<f))
                words.append(y)
            self.prove(12,16,words,changed)

    def test_shared_signed_helpers_exact_domain(self):
        helpers=[]
        for name, op, scalar in [('fp_add','+',False),('fp_sub','-',False),
                                 ('fp_gt','>',True),('fp_lt','<',True),
                                 ('fp_ge','>=',True),('fp_le','<=',True)]:
            result='' if scalar else 'signed [63:0] '
            helpers.append(f'''function {result}{name};
  input signed [63:0] a, b;
  begin {name} = a {op} b; end
endfunction
''')
        source='module top(input [7:0] x, output [65:0] y);\n'+''.join(helpers)+'''
  wire signed [63:0] a = $signed(x[3:0]);
  wire signed [63:0] b = $signed(x[7:4]);
  assign y = {fp_gt(a,b),fp_ge(a,b),fp_sub(a,b)};
endmodule
'''
        changed=share_signed_operators(source)
        self.assertIn('fp_sub = fp_add(a, -b)',changed)
        self.assertIn('fp_gt = fp_lt(b, a)',changed)
        self.assertIn('fp_ge = fp_le(b, a)',changed)
        for scale in (0,60):
            scaled=changed.replace('$signed(x[3:0])',f'($signed(x[3:0]) <<< {scale})').replace(
                '$signed(x[7:4])',f'($signed(x[7:4]) <<< {scale})')
            words=[]
            for x in range(256):
                a,b=x&15,x>>4
                a=(a-16 if a>=8 else a) << scale
                b=(b-16 if b>=8 else b) << scale
                words.append((int(a>b)<<65)+(int(a>=b)<<64)+((a-b)&((1<<64)-1)))
            self.prove(8,66,words,scaled)

    def test_shared_widened_arithmetic_preserves_context_and_wrap(self):
        helpers='''  function signed [63:0] fp_add;
    input signed [63:0] a, b;
    begin fp_add = a + b; end
  endfunction
  function signed [63:0] fp_mul;
    input signed [63:0] a, b;
    begin fp_mul = a * b; end
  endfunction
  function signed [63:0] mul_q62;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q62 = product / 128'sd4611686018427387904;
    end
  endfunction
'''
        source=self.kernel().replace('output reg [15:0] y','output reg [255:0] y')
        source=source.replace('source, first, rounded, rem;','source, first, rounded, rem, b;')
        source=source.replace('  always @(*) begin',helpers+'  always @(*) begin')
        source=source.replace('source = $signed(x);',
            'source = $signed(x[3:0]) <<< 60; b = $signed(x[7:4]) <<< 60;')
        source=source.replace('y = rounded;','y = {mul_q62(source,b),fp_mul(source,b),fp_add(source,b),rounded};')
        changed=share_signed_operators(share_round_to_even(source))
        self.assertIn('semantic_add65(extended, bias)',changed)
        self.assertIn('product = semantic_multiply128(a, b)',changed)
        def rnd(v,s):
            q=v>>s;r=v-(q<<s);h=1<<(s-1)
            return q+int(r>h or r==h and q&1)
        for scale in (0,60):
            words=[]; mask=(1<<64)-1
            for x in range(256):
                a,b=x&15,x>>4
                a=(a-16 if a>=8 else a)<<scale
                b=(b-16 if b>=8 else b)<<scale
                p=a*b; q=abs(p)//(1<<62)
                if p<0:q=-q
                words.append(((q&mask)<<192)+((p&mask)<<128)+(((a+b)&mask)<<64)+
                             (rnd(rnd(a,3),1)&mask))
            self.prove(8,256,words,changed.replace('<<< 60',f'<<< {scale}'))

    def test_linear_pack_unknown_guard_unchanged(self):
        source='''module top(input [7:0] x, output reg [15:0] y);
  reg signed [63:0] bin_exp, out_exp, rounded;
  always @(*) begin
    rounded=128+x[6:0]; bin_exp=x[7]?-126:-125; out_exp=0;
    if(rounded>=256) begin rounded=128; bin_exp=bin_exp+1; end
    out_exp=bin_exp+127;
    if(out_exp<=0) y=0;
    else if(out_exp>=255) y=16'h7f80;
    else if(out_exp==1) y=0;
    else y={out_exp[7:0],rounded[6:0]};
  end
endmodule
'''
        self.assertEqual(linearize_float_pack(source),source)

    def test_linear_pack_signed_word_arithmetic(self):
        source='''module top(input [11:0] x, output reg [15:0] y);
  wire sign = x[11];
  reg signed [63:0] bin_exp, out_exp, rounded;
  always @(*) begin
    bin_exp = $signed({1'b0,x[10:9]}) - 128;
    rounded = 128+x[6:0]+x[7]; out_exp=0;
    if(rounded>=256) begin rounded=128; bin_exp=bin_exp+1; end
    out_exp=bin_exp+127;
    if(out_exp<=0) y=0;
    else if(out_exp>=255) y=16'h7f80;
    else y={sign,out_exp[7:0],rounded[6:0]};
  end
endmodule
'''
        changed=linearize_float_pack(source)
        self.assertIn("y = sign * 16'd32768 + semantic_packed_magnitude;",changed)
        words=[]
        for x in range(4096):
            exponent=((x>>9)&3)-1
            rounded=128+(x&127)+((x>>7)&1)
            if rounded>=256:
                rounded=128; exponent+=1
            words.append(0 if exponent<=0 else ((x>>11)<<15)+exponent*128+(rounded&127))
        self.prove(12,16,words,changed)

    def test_square_halfway_quotient_even_all_significands(self):
        ties=0
        for fraction_width in range(1,13):
            for significand in range(1<<fraction_width,2<<fraction_width):
                product=significand*significand
                normalize=int(product >= 1<<(2*fraction_width+1))
                shift=fraction_width+normalize
                quotient,remainder=divmod(product,1<<shift)
                half=1<<(shift-1)
                if remainder==half:
                    ties+=1
                    self.assertEqual(quotient % 2,0)
                nearest=quotient+int(remainder>half or remainder==half and quotient&1)
                self.assertEqual((product+half-1)>>shift,nearest)
        self.assertGreater(ties,0)

    def prove(self, n, m, words, rtl):
        with tempfile.TemporaryDirectory() as directory:
            truth, source = Path(directory) / 'input.truth', Path(directory) / 'candidate.v'
            mask = (1 << n) - 1
            truth.write_text('\n'.join(''.join(str((words[x ^ mask] >> bit) & 1)
                                               for x in range(1 << n))
                                       for bit in range(m)) + '\n')
            source.write_text(rtl)
            result = verify(truth, source, default_yosys(), use_cache=False)
            self.assertEqual(result['frontend'], 'pass', result)
            self.assertEqual(result['status'], 'pass', result)
            self.assertEqual(result['vectors'], 1 << n)


if __name__ == '__main__':
    unittest.main()

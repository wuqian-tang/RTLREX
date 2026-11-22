"""Exhaustive real-Yosys checks of signed modular word lowering."""
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from support import tool_path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/circuit-reverse-rtl/scripts'))
from verify.algebraic.certificate import word_poly

class SignedWordTests(unittest.TestCase):
    def lower(self, body, aw=3, bw=3, yw=8):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)/'candidate.v'
            dst = Path(tmp)/'design.json'
            src.write_text(f'module top(a,b,y); input [{aw-1}:0] a; input [{bw-1}:0] b; output [{yw-1}:0] y;\n'+body+'\nendmodule\n')
            subprocess.run([str(tool_path('yosys')), '-Q', '-T', '-p', f'read_verilog {src}; hierarchy -top top; proc; opt; write_json {dst}'], check=True, capture_output=True)
            return word_poly(json.loads(dst.read_text())['modules']['top'], yw)[0]['y']
    def verify_all(self, poly, expected, aw=3, bw=3, yw=8):
        for a,b in itertools.product(range(1<<aw),range(1<<bw)):
            assignment={f'a[{i}]':(a>>i)&1 for i in range(aw)}
            assignment.update({f'b[{i}]':(b>>i)&1 for i in range(bw)})
            actual=sum(c for t,c in poly.items() if all(assignment[x] for x in t)) % (1<<yw)
            self.assertEqual(actual,expected(a,b) % (1<<yw),(a,b))
    @staticmethod
    def signed(x,w=3): return x-(1<<w) if x>>(w-1) else x
    def test_signed_product_sign_extension(self):
        p=self.lower('wire signed [2:0] sa=a,sb=b; wire signed [5:0] prod=sa*sb; assign y=prod;')
        self.verify_all(p,lambda a,b:self.signed(a)*self.signed(b))
    def test_signed_difference_product(self):
        p=self.lower('wire signed [2:0] sa=a,sb=b; wire signed [3:0] d=sa-sb; wire signed [6:0] prod=d*sb; assign y=prod;')
        self.verify_all(p,lambda a,b:(self.signed(a)-self.signed(b))*self.signed(b))
    def test_full_ring_signed_wrap(self):
        p=self.lower('wire signed [2:0] sa=a,sb=b; assign y=sa*sb+sa;',yw=4)
        self.verify_all(p,lambda a,b:self.signed(a)*self.signed(b)+self.signed(a),yw=4)
    def test_wide_primary_sign_extension(self):
        p=self.lower('wire signed [7:0] sa=$signed(a),sb=$signed(b); assign y=sa*sb;')
        self.verify_all(p,lambda a,b:self.signed(a)*self.signed(b))
    def test_unsigned_zero_extension_with_signed_product(self):
        p=self.lower('wire signed [2:0] sa=a,sb=b; wire signed [5:0] prod=sa*sb; wire [7:0] term=prod; wire [5:0] u=a*b; assign y=term+u;')
        self.verify_all(p,lambda a,b:self.signed(a)*self.signed(b)+a*b)
    def test_narrow_overflow_rejected(self):
        with self.assertRaises(AssertionError):
            self.lower('wire signed [2:0] sa=a,sb=b; wire signed [3:0] prod=sa*sb; assign y=prod;')
    def test_negative_zero_extension_rejected(self):
        with self.assertRaises(AssertionError):
            self.lower('wire signed [2:0] sa=a,sb=b; wire [5:0] prod=sa*sb; assign y=prod;')
    def test_right_shift_rejected(self):
        with self.assertRaises(AssertionError):
            self.lower('wire signed [2:0] sa=a,sb=b; wire signed [5:0] prod=sa*sb; assign y=prod >>> 1;')
    def test_end_to_end_signed_certificate_and_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            ref=tmp/'reference.v'
            lines=['module top(a,b,y); input [1:0] a,b; output [4:0] y;']
            names=['a[0]','a[1]','b[0]','b[1]']
            for i,n in enumerate(names): lines += [f'wire inv{i};',f'not neg{i}(inv{i},{n});']
            columns=[[] for _ in range(5)]
            for m in range(16):
                args=[names[i] if (m>>i)&1 else f'inv{i}' for i in range(4)]
                lines += [f'wire row{m};',f'and r{m}(row{m},'+','.join(args)+');']
                v=(self.signed(m&3,2)*self.signed(m>>2,2))&31
                for i in range(5):
                    if (v>>i)&1: columns[i].append(f'row{m}')
            for i,col in enumerate(columns): lines.append(f'or out{i}(y[{i}],'+','.join(col)+');')
            ref.write_text('\n'.join(lines+['endmodule']))
            from verify.algebraic import cuts,certificate
            identities=tmp/'identities.json'
            identities.write_text(json.dumps(cuts.extract(ref)))
            for suffix,expr,success in [('good','p',True),('bad',"p+5'd1",False)]:
                cand=tmp/(suffix+'.v')
                cand.write_text('module top(a,b,y); input [1:0] a,b; output [4:0] y; wire signed [1:0] sa=a,sb=b; wire signed [3:0] p=sa*sb; assign y='+expr+'; endmodule')
                item={'input_path':str(ref),'candidate_path':str(cand),'input_sha256':certificate.sha(ref),'candidate_sha256':certificate.sha(cand)}
                if success:
                    record=certificate.verify(item,identities,tmp/suffix,yosys=tool_path('yosys'),sliced_outputs={'y'})
                    self.assertTrue(record['all_original_outputs_compared'])
                    self.assertEqual(record['status'],'strict_algebraic_equivalence')
                else:
                    with self.assertRaises(AssertionError): certificate.verify(item,identities,tmp/suffix,yosys=tool_path('yosys'),sliced_outputs={'y'})

    def test_sign_mutation_changes_polynomial(self):
        good=self.lower('wire signed [2:0] sa=a,sb=b; wire signed [5:0] prod=sa*sb; assign y=prod;')
        bad=self.lower('wire signed [3:0] sa={1\'b0,a},sb={1\'b0,b}; wire signed [7:0] prod=sa*sb; assign y=prod;')
        self.assertNotEqual(good,bad)

if __name__=='__main__': unittest.main()

"""Integration checks for the complete-output small-PI proof route."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
REFERENCE='''module top(a,b,y,z);
input a,b;
output [1:0] y,z;
xor g0(y[0],a,b);
and g1(y[1],a,b);
and g2(z[0],a,b);
buf g3(z[1],1'b0);
endmodule
'''
class SmallPIBackendTests(unittest.TestCase):
    def run_case(self, z, extra=()):
        with tempfile.TemporaryDirectory() as name:
            d=Path(name);ref=d/'ref.v';cand=d/'cand.v';ref.write_text(REFERENCE)
            cand.write_text('module top(a,b,y,z); input a,b; output [1:0] y,z; assign y=a+b; assign z='+z+'; endmodule')
            command=['python3',str(ROOT/'skills/circuit-reverse-rtl/scripts/cec.py'),str(ref),str(cand),'--engine','algebraic-cones','--algebraic-timeout','10','--keep-tmp','--tmpdir',str(d/'proof'),'--json',*extra]
            p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=20)
            return p,json.loads(p.stdout) if p.stdout.strip().startswith('{') else None
    def test_complete_proof(self):
        p,r=self.run_case('a*b')
        self.assertEqual(r['status'],'pass',r)
        self.assertIs(r['equivalent'],True)
    def test_all_output_mutation_is_not_hidden(self):
        p,r=self.run_case("a*b+2'd2")
        self.assertNotEqual(r['status'],'pass');self.assertIsNot(r['equivalent'],True)
    def test_case_split_cannot_be_silently_ignored(self):
        p,r=self.run_case("2'b00",['--algebraic-case-split-bit','a'])
        self.assertEqual(r['status'],'error');self.assertIn('unsupported',r['error'])
    def test_invalid_support_cap_rejected(self):
        p,r=self.run_case("2'b00",['--algebraic-cone-input-cap','9'])
        self.assertNotEqual(p.returncode,0);self.assertIsNone(r)
if __name__=='__main__':unittest.main()

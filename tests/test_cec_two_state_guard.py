"""Undefined-value and valid two-state controls through the public CEC CLI."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CEC=ROOT/'skills/circuit-reverse-rtl/scripts/verify/cec.py'
class TwoStateOutputGuard(unittest.TestCase):
 def run_pair(self,body,expected="assign y=1'b0;",out_format='aiger'):
  with tempfile.TemporaryDirectory() as td:
   d=Path(td);header='module top(a,y); input a; output y; '
   (d/'ref.v').write_text(header+body+' endmodule\n');(d/'cand.v').write_text(header+expected+' endmodule\n')
   p=subprocess.run([sys.executable,str(CEC),str(d/'ref.v'),str(d/'cand.v'),'--engine','cec','--strict-cec','--format',out_format,'--timeout','15','--abc-timeout','15','--json'],capture_output=True,text=True,timeout=40)
   return json.loads(p.stdout)
 def test_explicit_x(self):
  r=self.run_pair("assign y=1'bx;");self.assertNotEqual(r['status'],'pass');self.assertIn('X/Z',r['abc_output'])
 def test_explicit_z(self):
  r=self.run_pair("assign y=1'bz;");self.assertNotEqual(r['status'],'pass');self.assertIn('X/Z',r['abc_output'])
 def test_x_through_combinational_cell(self):
  r=self.run_pair("wire [1:0] sum; assign sum={1'b0,a}+2'b0x; assign y=sum[1];");self.assertNotEqual(r['status'],'pass');self.assertIn('X/Z',r['abc_output'])
 def test_optimized_dontcare_mux(self):
  r=self.run_pair("assign y=a ? 1'bx : 1'b0;");self.assertNotEqual(r['status'],'pass');self.assertTrue("X/Z" in r["abc_output"] or "'x' or 'z'" in r["abc_output"])
 def test_blif_cannot_bypass(self):
  r=self.run_pair("assign y=1'bx;",out_format='blif');self.assertNotEqual(r['status'],'pass');self.assertIn('X/Z',r['abc_output'])
 def test_dead_x_does_not_reject_two_state_outputs(self):
  r=self.run_pair("wire unused; assign unused=1'bx; assign y=a^a;");self.assertEqual(r['status'],'pass',r)
 def test_valid_two_state_nonconstant(self):
  r=self.run_pair('assign y=~a;',expected="assign y=a^1'b1;");self.assertEqual(r['status'],'pass',r)
 def test_undriven_reachable_net(self):
  r=self.run_pair('wire u; assign y=a^u;');self.assertNotEqual(r['status'],'pass');self.assertIn('undriven',r['abc_output'])
 def test_old_array_dimension_mistake(self):
  r=self.run_pair('wire po[2],po[3]; buf b(po[3],a); assign y=po[3];');self.assertNotEqual(r['status'],'pass');self.assertIn('X/Z',r['abc_output'])
if __name__=='__main__':unittest.main()

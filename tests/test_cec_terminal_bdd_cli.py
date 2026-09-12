"""ROBDD coefficient options must reach the public terminal verifier only."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CEC=ROOT/'skills/circuit-reverse-rtl/scripts/cec.py'
class TerminalBDDCLI(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name);self.ref=self.d/'ref.v';self.cand=self.d/'cand.v'
  h='module top(a,y); input [6:0] a; output [0:0] y; '
  self.ref.write_text(h+'xor g(y[0], '+','.join(f'a[{i}]' for i in range(7))+'); endmodule\n')
  self.cand.write_text(h+'assign y='+'+'.join(f'a[{i}]' for i in range(7))+'; endmodule\n')
 def tearDown(self):self.tmp.cleanup()
 def runproof(self,extra=(),engine='algebraic-terminal'):
  cmd=[sys.executable,str(CEC),str(self.ref),str(self.cand),'--engine',engine,'--strict-cec','--algebraic-coefficient-input','a','--algebraic-coefficient-engine','bdd','--algebraic-timeout','20','--tmpdir',str(self.d/'proof'),'--keep-tmp','--json',*extra]
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=35);return json.loads(p.stdout)
 def test_full_native_parity_positive_and_option_forwarding(self):
  r=self.runproof(['--algebraic-bdd-order','port-major','--algebraic-bdd-node-cap','10000']);self.assertEqual(r['status'],'pass',r)
  proof=json.loads(next((self.d/'proof').glob('*/proof/result.json')).read_text());self.assertEqual(proof['coefficient_engine'],'bdd');self.assertGreater(proof['coefficient_count'],0);self.assertTrue(proof['strict'])
  command=json.loads(next((self.d/'proof').glob('*/command.json')).read_text());self.assertEqual(command[command.index('--bdd-order')+1],'port-major');self.assertEqual(command[command.index('--bdd-node-cap')+1],'10000')
 def test_wrong_parity_rejected(self):
  self.cand.write_text(self.cand.read_text().replace('assign y=','assign y=1+'));r=self.runproof();self.assertNotEqual(r['status'],'pass')
 def test_exhausted_nodes_cannot_pass(self):
  r=self.runproof(['--algebraic-bdd-node-cap','2']);self.assertNotEqual(r['status'],'pass');self.assertIn('node cap',r['error'])
 def test_nonterminal_engine_rejects_coefficient_options(self):
  for engine in ['auto','algebraic','algebraic-cones','sat-bits','smt']:
   r=self.runproof(engine=engine);self.assertEqual(r['status'],'configuration_error');self.assertIn('require algebraic-terminal',r['error'])
if __name__=='__main__':unittest.main()

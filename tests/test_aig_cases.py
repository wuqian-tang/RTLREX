from pathlib import Path
import copy,json,subprocess,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'skills/circuit-reverse-rtl/scripts'));from verify import aig_cases as ac
class ExactAigCaseTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name);self.graph={'I':2,'O':2,'M':5,'outputs':[10,6],'gates':[(4,2),(5,3),(9,7)],'symbols':{'i':{0:'a',1:'b'},'o':{0:'sum',1:'carry'}}};self.ref=self.d/'reference.aig';self.cand=self.d/'candidate.aig';ac.cofactor(self.graph,self.ref,{});ac.cofactor(self.graph,self.cand,{});self.counter=0
 def tearDown(self):self.tmp.cleanup()
 def run_checker(self,manifest=None,candidate=None,extra=()):
  self.counter+=1;out=self.d/f'run_{self.counter}';cmd=[sys.executable,str(R/'skills/circuit-reverse-rtl/scripts/verify/aig_cases.py'),'--reference-aig',str(self.ref),'--candidate-aig',str(candidate or self.cand),'--split-input','a','--out',str(out),'--timeout','10','--branch-timeout','2',*extra]
  if manifest:cmd+=['--replay-manifest',str(manifest)]
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=20);return p,json.loads((out/'result.json').read_text()),out
 def valid_archive(self):
  p,r,out=self.run_checker();self.assertEqual(p.returncode,0);self.assertTrue(r['strict']);return json.loads((out/'archive.json').read_text())
 def save_manifest(self,m):p=self.d/'edited.json';p.write_text(json.dumps(m));return p
 def test_fresh_and_archived_full_output_scope(self):
  m=self.valid_archive();p,r,_=self.run_checker(self.save_manifest(m));self.assertEqual(p.returncode,0);self.assertTrue(r['all_original_inputs_free']);self.assertEqual(r['all_original_output_bits_compared'],2);self.assertEqual(r['execution_mode'],'archived_solver_replay_with_fresh_independent_cofactor_audit')
 def test_last_output_actual_mutation_rejected(self):
  g=copy.deepcopy(self.graph);g['outputs'][-1]^=1;bad=self.d/'wrong.aig';ac.cofactor(g,bad,{});p,r,_=self.run_checker(candidate=bad);self.assertNotEqual(p.returncode,0);self.assertFalse(r['strict'])
 def test_missing_cube_rejected(self):
  m=self.valid_archive();m['branches'].pop();p,r,_=self.run_checker(self.save_manifest(m));self.assertFalse(r['strict']);self.assertIn('coverage',r['reason'])
 def test_wrong_source_rejected(self):
  m=self.valid_archive();g=copy.deepcopy(self.graph);g['outputs'][0]^=1;bad=self.d/'different.aig';ac.cofactor(g,bad,{});p,r,_=self.run_checker(self.save_manifest(m),candidate=bad);self.assertFalse(r['strict']);self.assertIn('source pair differs',r['reason'])
 def test_forged_cofactor_with_updated_hash_rejected(self):
  m=self.valid_archive();q=Path(m['branches'][0]['candidate']['path']);g=ac.read_aig(q);g['outputs'][-1]^=1;bad=self.d/'changed_cofactor.aig';ac.cofactor(g,bad,{});m['branches'][0]['candidate']=ac.artifact(bad);p,r,_=self.run_checker(self.save_manifest(m));self.assertFalse(r['strict']);self.assertIn('cofactor identity',r['reason'])
 def test_nonzero_worker_result_cannot_reuse_pass_log(self):
  m=self.valid_archive();m['branches'][0]['returncode']=7;p,r,_=self.run_checker(self.save_manifest(m));self.assertFalse(r['strict']);self.assertIn('strictly prove',r['reason'])
 def test_duplicate_split_symbol_rejected(self):
  p,r,_=self.run_checker(extra=['--split-input','a']);self.assertFalse(r['strict']);self.assertIn('distinct',r['reason'])
 def test_whole_process_watchdog_fails_closed(self):
  p,r,_=self.run_checker(extra=['--timeout','0.001']);self.assertFalse(r['strict']);self.assertIn('process-group timeout',r['reason'])
if __name__=='__main__':unittest.main()

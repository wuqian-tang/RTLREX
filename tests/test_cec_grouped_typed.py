"""Real positive and adversarial controls for generic grouped/product checkers."""
import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];VERIFY=ROOT/'skills/circuit-reverse-rtl/scripts/verify';sys.path.insert(0,str(VERIFY.parent))
from verify.composition import sha
from verify.algebraic import cuts
from verify.grouped_algebraic import substitute
class NewProofPlans(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.d=Path(self.t.name)
 def tearDown(self):self.t.cleanup()
 def art(self,p):return {'path':str(p),'sha256':sha(p)}
 def grouped(self,bad=False):
  r=self.d/'r.v';c=self.d/'c.v';r.write_text("module top(a,b,y); input [1:0] a,b; output [2:0] y; wire c0,t,p,q,r; xor g0(y[0],a[0],b[0]); and g1(c0,a[0],b[0]); xor g2(t,a[1],b[1]); xor g3(y[1],t,c0); and g4(p,a[1],b[1]); and g5(q,a[1],c0); and g6(r,b[1],c0); or g7(y[2],p,q,r); endmodule\n");c.write_text("module top(a,b,y); input [1:0] a,b; output [2:0] y; assign y={1'b0,a[1],a[0]}+{1'b0,b}"+("+3'd1" if bad else '')+"; endmodule\n")
  plan={'schema':'exact-grouped-algebraic/v1','reference':self.art(r),'candidate':self.art(c),'fixed_bits':['a[1]'],'groups':[]}
  for value in (0,1):
   folder=self.d/f'g{value}';folder.mkdir();gr=folder/'r.v';gc=folder/'c.v';assignment={'a[1]':value};gr.write_text(substitute(r.read_text(),assignment));gc.write_text(substitute(c.read_text(),assignment));ident=folder/'ids.json';ident.write_text(json.dumps(cuts.extract(gr,48)));plan['groups'].append({'assignment':assignment,'reference':self.art(gr),'candidate':self.art(gc),'identities':self.art(ident),'split_bits':['a[0]']})
  return plan
 def run_grouped(self,plan):
  p=self.d/'plan.json';p.write_text(json.dumps(plan));out=self.d/'out';subprocess.run([sys.executable,str(VERIFY/'grouped_algebraic.py'),'--plan',str(p),'--out',str(out),'--timeout','10','--jobs','2'],capture_output=True,text=True,timeout=40);return json.loads((out/'result.json').read_text())
 def test_full_grouped_replay(self):
  r=self.run_grouped(self.grouped());self.assertEqual(r['status'],'pass',r);self.assertEqual(r['total_leaf_assignments'],4)
 def test_relative_plan_artifacts(self):
  p=self.grouped()
  for record in [p['reference'],p['candidate']]+[g[key] for g in p['groups'] for key in ['reference','candidate','identities']]:
   record['path']=str(Path(record['path']).relative_to(self.d))
  r=self.run_grouped(p);self.assertEqual(r['status'],'pass',r);self.assertEqual(r['total_leaf_assignments'],4)
 def test_missing_outer_group(self):
  p=self.grouped();p['groups'].pop();self.assertFalse(self.run_grouped(p)['strict'])
 def test_duplicate_outer_assignment(self):
  p=self.grouped();p['groups'][1]=p['groups'][0];self.assertFalse(self.run_grouped(p)['strict'])
 def test_bad_function_fails_fresh_replay(self):self.assertFalse(self.run_grouped(self.grouped(True))['strict'])
 def test_unrecorded_group_output_edit(self):
  p=self.grouped();g=p['groups'][0];f=Path(g['candidate']['path']);f.write_text(f.read_text().replace("+{1'b0,b}","+{1'b0,b}+3'd1"));g['candidate']=self.art(f);self.assertFalse(self.run_grouped(p)['strict'])
 def test_string_literal_not_cofactored(self):
  p=self.grouped();f=Path(p['candidate']['path']);f.write_text(f.read_text().replace("assign y=", 'assign y="a[1]"+'));p['candidate']=self.art(f);r=self.run_grouped(p);self.assertFalse(r['strict']);self.assertIn('strings unsupported',r['reason'])
 def test_late_input_driver_rejected(self):
  p=self.grouped();f=Path(p['reference']['path']);text=f.read_text().replace('input [1:0] a,b;', "buf bad(a[1],1'b0); input [1:0] a,b;");f.write_text(text);p['reference']=self.art(f);r=self.run_grouped(p);self.assertFalse(r['strict']);self.assertIn('drives an input',r['reason'])
 def test_literal_driver_rejected(self):
  p=self.grouped();f=Path(p['reference']['path']);f.write_text(f.read_text().replace('endmodule',"buf bad(1'b0,a[0]); endmodule"));p['reference']=self.art(f);r=self.run_grouped(p);self.assertFalse(r['strict']);self.assertIn('drives a literal',r['reason'])
 def typed(self,bad=False):
  left=self.d/'left.v';right=self.d/'right.v';header='module top(a,b,y); input [1:0] a; input [2:0] b; output [3:0] y; '
  left.write_text(header+'wire [4:0] p; assign p=a*b; assign y=p[3:0]; endmodule\n');right.write_text(header+'wire [3:0] p; assign p='+('b*b' if bad else 'a*b')+'; assign y=p; endmodule\n');out=self.d/'out';subprocess.run([sys.executable,str(VERIFY/'typed_product.py'),'--left',str(left),'--right',str(right),'--out',str(out)],capture_output=True,text=True,timeout=20);return json.loads((out/'result.json').read_text())
 def test_typed_native_prefix(self):
  r=self.typed();self.assertEqual(r['status'],'pass',r);self.assertEqual(r['native_widths'],[5,4])
 def test_typed_wrong_input(self):self.assertFalse(self.typed(True)['strict'])
if __name__=='__main__':unittest.main()

"""Real full-interface controls for proposed embeddings and ripple normalization."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/circuit-reverse-rtl/scripts'))
from verify.composition import sha
VERIFY=ROOT/'skills/circuit-reverse-rtl/scripts/verify'
class Plans(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def art(self,p):return {'path':str(p),'sha256':sha(p)}
    def run_plan(self,name,plan):
        p=self.d/'plan.json';p.write_text(json.dumps(plan));r=subprocess.run([sys.executable,str(VERIFY/(name+'.py')),'--plan',str(p),'--out',str(self.d/'proof'),'--timeout','15'],capture_output=True,text=True,timeout=120)
        return json.loads((self.d/'proof/result.json').read_text())
    def embedding(self):
        r=self.d/'ref.v';c=self.d/'cand.v';e=self.d/'embed.v';w=self.d/'word.v'
        r.write_text('module top(a,b,out); input a,b; output out; and g(out,a,b); endmodule\n')
        c.write_text('module top(a,b,out); input a,b; output out; assign out=a&b; endmodule\n')
        e.write_text('module top(a,b,wide); input a,b; output [1:0] wide; wire out; and g(out,a,b); xor s(wide[0],a,b); buf hi(wide[1],out); endmodule\n')
        w.write_text("module top(a,b,wide); input a,b; output [1:0] wide; assign wide={1'b0,a}+{1'b0,b}; endmodule\n")
        return {'reference':self.art(r),'candidate':self.art(c),'embedded_reference':self.art(e),'word_candidate':self.art(w),'low_bits':1,'engine':'algebraic'}
    def test_embedding_positive(self):
        r=self.run_plan('embedded_word',self.embedding());self.assertEqual(r['status'],'pass',r);self.assertEqual(r['original_output_bits'],1)
    def test_embedding_original_gate_mutation(self):
        p=self.embedding();e=self.d/'embed.v';e.write_text(e.read_text().replace('and g','or g'));p['embedded_reference']=self.art(e);r=self.run_plan('embedded_word',p);self.assertFalse(r['strict'])
    def test_embedding_high_connection_mutation(self):
        p=self.embedding();e=self.d/'embed.v';e.write_text(e.read_text().replace('buf hi','not hi'));p['embedded_reference']=self.art(e);r=self.run_plan('embedded_word',p);self.assertFalse(r['strict'])
    def test_embedding_retained_candidate_mutation(self):
        p=self.embedding();c=self.d/'cand.v';c.write_text(c.read_text().replace('a&b','a|b'));p['candidate']=self.art(c);r=self.run_plan('embedded_word',p);self.assertFalse(r['strict'])
    def normalizer(self):
        r=self.d/'ref.v';r.write_text('module top(a,b,s,z); input a,b; output [1:0] s; output z; xor g(s[0],a,b); and h(s[1],a,b); buf zz(z,s[1]); endmodule\n')
        return {'reference':self.art(r),'output_name':'s','cutnames':['a','b'],'weights':[1,1],'constant':0}
    def test_normalization_keeps_other_output_fanout(self):
        r=self.run_plan('normalize_final_adder',self.normalizer());self.assertEqual(r['status'],'pass',r);self.assertTrue(r['all_original_outputs_compared'])
    def test_normalization_wrong_affine_constant(self):
        p=self.normalizer();p['constant']=1;r=self.run_plan('normalize_final_adder',p);self.assertFalse(r['strict'])
    def test_normalization_circular_cut(self):
        p=self.normalizer();p['cutnames']=['s[0]','b'];r=self.run_plan('normalize_final_adder',p);self.assertFalse(r['strict'])
if __name__=='__main__':unittest.main()

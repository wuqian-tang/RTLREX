"""End-to-end controls for complete RTL chains and explicit tap proofs."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support import tool_path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/circuit-reverse-rtl/scripts'))
from verify.composition import read_aig, sha
from verify.cec import lower_with_yosys
VERIFY=ROOT/'skills/circuit-reverse-rtl/scripts/verify'
YOSYS=tool_path('yosys')


class Routes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.d=Path(self.temp.name)
        text="module top(a,b,s,z); input [1:0] a,b; output [2:0] s; output z; assign s={1'b0,a}+{1'b0,b}; assign z=a[0]^b[1]; endmodule\n"
        self.a=self.d/'a.v';self.b=self.d/'b.v';self.c=self.d/'c.v'
        for p in (self.a,self.b,self.c):p.write_text(text)
    def tearDown(self):self.temp.cleanup()
    def art(self,p):return {'path':str(p),'sha256':sha(p)}
    def run_plan(self,module,plan):
        p=self.d/'plan.json';p.write_text(json.dumps(plan))
        args=[sys.executable,str(VERIFY/(module+'.py')),'--plan',str(p),'--out',str(self.d/'run'),'--timeout','10']
        if module=='composition':args+=['--yosys',str(YOSYS)]
        run=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=120)
        record=json.loads((self.d/'run/result.json').read_text())
        return run.returncode,record
    def chain(self):return {'schema':'exact-rtl-chain/v1','nodes':[self.art(p) for p in (self.a,self.b,self.c)],'edges':[{'engine':'auto'},{'engine':'auto'}]}
    def test_chain_full_positive(self):
        rc,r=self.run_plan('chain',self.chain());self.assertEqual(rc,0);self.assertTrue(r['all_original_outputs_compared'])
    def test_chain_last_output_mutation(self):
        self.c.write_text(self.c.read_text().replace('a[0]^b[1]','~(a[0]^b[1])'))
        rc,r=self.run_plan('chain',self.chain());self.assertNotEqual(rc,0);self.assertFalse(r['strict'])
    def test_chain_missing_edge(self):
        p=self.chain();p['edges'].pop();rc,r=self.run_plan('chain',p);self.assertNotEqual(rc,0)
    def test_chain_wrong_hash(self):
        p=self.chain();p['nodes'][1]['sha256']='0'*64;rc,r=self.run_plan('chain',p);self.assertNotEqual(rc,0)
    def composition(self):
        a=self.d/'a.aig';b=self.d/'b.aig'
        for source,target in [(self.a,a),(self.b,b)]:self.assertEqual(lower_with_yosys(YOSYS,source,target,'aiger',10).returncode,0)
        g=read_aig(a);sel=sorted([i for i,n in g['symbols']['o'].items() if n.startswith('s[')],key=lambda i:int(g['symbols']['o'][i][2:-1]))
        bridge=self.d/'bridge.v';word=self.d/'word.v';ix={v:k for k,v in g['symbols']['i'].items()}
        lines=['module top(pi,po); input [3:0] pi; output [2:0] po; wire [1:0] a,b; wire [2:0] s;']
        for n in ['a','b']:lines.append(f'assign {n}={{pi[{ix[n+"[1]"]}],pi[{ix[n+"[0]"]}]}};')
        lines+= ["assign s={1'b0,a}+{1'b0,b};",'assign po={'+','.join(g['symbols']['o'][i] for i in reversed(sel))+'};','endmodule']
        bridge.write_text('\n'.join(lines));word.write_text('module top(pi,po); input [6:0] pi; output [2:0] po; assign po=pi[6:4]; endmodule\n')
        return {'reference_aig':self.art(a),'candidate_aig':self.art(b),'original_reference':self.art(self.a),'original_candidate':self.art(self.b),'bridge_rtl':self.art(bridge),'word_stage_rtl':self.art(word),'tap_literals':[g['outputs'][i] for i in sel],'word_outputs':sel,'tap_engine':'algebraic','tap_word_widths':[3],'word_engine':'auto'}
    def test_composition_grouped_full_positive(self):
        rc,r=self.run_plan('composition',self.composition());self.assertEqual(rc,0,r);self.assertTrue(r['original_rtl_bound']);self.assertEqual(r['original_output_bits'],4)
    def test_composition_unsupported_partial_word(self):
        p=self.composition();p['tap_word_widths']=[1,2];rc,r=self.run_plan('composition',p);self.assertNotEqual(rc,0)
    def test_composition_missing_group_bit(self):
        p=self.composition();p['tap_word_widths']=[1,1];rc,r=self.run_plan('composition',p);self.assertNotEqual(rc,0)
    def test_composition_wrong_original_binding(self):
        p=self.composition();self.b.write_text(self.b.read_text().replace('a[0]^b[1]','~(a[0]^b[1])'));p['original_candidate']=self.art(self.b)
        rc,r=self.run_plan('composition',p);self.assertNotEqual(rc,0);self.assertFalse(r['strict'])
    def test_composition_wrong_word_stage(self):
        p=self.composition();w=self.d/'word.v';w.write_text(w.read_text().replace('pi[6:4]','pi[6:4]^3\'b100'));p['word_stage_rtl']=self.art(w)
        rc,r=self.run_plan('composition',p);self.assertNotEqual(rc,0)


if __name__=='__main__':unittest.main()

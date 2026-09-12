import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/circuit-reverse-rtl/scripts'))
from verify.algebraic_terminal import bdd

class NativeBDDTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)
        self.ref=self.d/'ref.v';self.groups=self.d/'groups.json'
        self.ref.write_text('module top(a,y); input [1:0] a; output [1:0] y; xor x(y[0],a[0],a[1]); and g(y[1],a[0],a[1]); endmodule\n')
        self.poly=[{'variables':[n],'coefficient':v} for n,v in [('a[0]',1),('a[1]',1),('y[0]',3),('y[1]',2)]]
        self.write()
    def tearDown(self):self.tmp.cleanup()
    def write(self):self.groups.write_text(json.dumps([{'outside_primary_monomial':[],'polynomial':self.poly}]))
    def runproof(self,**kw):return bdd.prove(self.ref,self.groups,{'a[0]','a[1]'},**kw)
    def test_full_adder_identity_direct_native_output_bits(self):
        for order in ['bit-major','port-major']:
            r=self.runproof(order=order);self.assertEqual(r['status'],'pass');self.assertTrue(r['groups'][0]['all_bits_zero'])
    def test_wrong_carry_rejected(self):
        self.poly[-1]['coefficient']=3;self.write()
        with self.assertRaisesRegex(ValueError,'nonzero coefficient'):self.runproof()
    def test_low_node_budget_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'node cap'):self.runproof(node_cap=2)
    def test_outside_primary_dependency_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside-domain'):bdd.prove(self.ref,self.groups,{'a[0]'})
    def test_duplicate_term_rejected(self):
        self.poly.append(self.poly[0]);self.write()
        with self.assertRaisesRegex(ValueError,'duplicate'):self.runproof()
    def test_non_boolean_variable_rejected(self):
        self.poly[0]['variables']=['missing'];self.write()
        with self.assertRaisesRegex(ValueError,'undefined'):self.runproof()
    def test_supported_operators_truth_tables(self):
        for op,table in [(6,lambda a,b:a^b),(8,lambda a,b:a&b),(14,lambda a,b:a|b)]:
            m=bdd.BDD(['a','b'],{}, {},100)
            node=m.apply(op,m.pics['a'],m.pics['b'])
            for a in (0,1):
                for b in (0,1):
                    q=node
                    while q>1:
                        v,lo,hi=m.nodes[q];q=(lo,hi)[(a,b)[v]]
                    self.assertEqual(q,table(a,b))

if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""Independent real-Yosys soundness regressions for output-bit SAT CEC."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import tool_path
ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT/'skills/circuit-reverse-rtl/scripts/verify/cec.py'
YOSYS = tool_path('yosys')

class RealSatBitsAudit(unittest.TestCase):
    def check(self, reference, implementation, total=15, engine='sat-bits', bit_timeout=1):
        with tempfile.TemporaryDirectory(prefix='independent_sat_audit_') as name:
            d=Path(name)
            (d/'ref.v').write_text(reference+'\n')
            (d/'impl.v').write_text(implementation+'\n')
            r=subprocess.run(['python3',str(CHECKER),str(d/'ref.v'),str(d/'impl.v'),
                              '--engine',engine,'--yosys',str(YOSYS),
                              '--sat-bit-timeout',str(bit_timeout),'--sat-total-timeout',str(total),
                              '--keep-tmp','--tmpdir',str(d/'artifacts'),'--json'],
                             cwd=ROOT,capture_output=True,text=True,timeout=total+30)
            result=json.loads(r.stdout)
            coverage=list((d/'artifacts').glob('*/coverage.json'))
            result['coverage']=json.loads(coverage[0].read_text()) if coverage else None
            return result

    def test_positive_all_outputs(self):
        r=self.check('module top(input a,b, output y,z); assign y=a&b; assign z=a^b; endmodule',
                     'module top(input a,b, output y,z); assign y=b&a; assign z=b^a; endmodule')
        self.assertEqual(r['status'],'pass')
        self.assertEqual(r['coverage']['proved_bits'],2)

    def test_last_output_cannot_be_omitted(self):
        r=self.check('module top(input [3:0] a, output [3:0] y, output z); assign y=a; assign z=a[3]; endmodule',
                     'module top(input [3:0] a, output [3:0] y, output z); assign y=a; assign z=~a[3]; endmodule')
        self.assertEqual(r['status'],'fail')
        self.assertEqual(r['coverage']['bits'][-1]['output'],'z')

    def test_last_bit_cannot_be_omitted(self):
        r=self.check('module top(input [3:0] a, output [3:0] y); assign y=a; endmodule',
                     "module top(input [3:0] a, output [3:0] y); assign y=a^4'b1000; endmodule")
        self.assertEqual(r['status'],'fail')
        self.assertEqual(r['coverage']['bits'][-1]['lsb_offset'],3)

    def test_unrelated_module_cannot_override_width(self):
        r=self.check('module top(a,y); input [3:0] a; output [3:0] y; assign y=a; endmodule\n'
                     'module ref_unused(a,y); input [3:0] a; output y; assign y=a[0]; endmodule',
                     "module top(a,y); input [3:0] a; output [3:0] y; assign y=a^4'b1000; endmodule\n"
                     'module impl_unused(a,y); input [3:0] a; output y; assign y=a[0]; endmodule')
        self.assertEqual(r['status'],'fail')
        self.assertEqual(r['coverage']['required_bits'],4)

    def test_packed_multidimensional_range_fails_closed(self):
        r=self.check('module top(input [1:0][3:0] a, output [1:0][3:0] y); assign y=a; endmodule',
                     "module top(input [1:0][3:0] a, output [1:0][3:0] y); assign y=a^8'h80; endmodule")
        self.assertNotEqual(r['status'],'pass')
        self.assertIsNot(r['equivalent'],True)

    def test_nested_function_cannot_restrict_input_width(self):
        template='module top(a,y); input [3:0] a; output y; assign y=%s; function f; input a; begin f=a; end endfunction endmodule'
        self.assertEqual(self.check(template%'a[3]',template%"1'b0")['status'],'fail')

    def test_signed_extension_is_checked(self):
        r=self.check('module top(input signed [3:0] a, output [4:0] y); assign y=a; endmodule',
                     "module top(input signed [3:0] a, output [4:0] y); assign y={1'b0,a}; endmodule")
        self.assertEqual(r['status'],'fail')

    def test_ascending_nonzero_range(self):
        ref='module top(input [0:3] a, output [7:10] y); assign y=a; endmodule'
        self.assertEqual(self.check(ref,ref)['status'],'pass')
        impl='module top(input [0:3] a, output [7:10] y); assign y={a[3],a[2],a[1],a[0]}; endmodule'
        self.assertEqual(self.check(ref,impl)['status'],'fail')

    def test_partial_bit_coverage_never_passes(self):
        ref='module top(input a, output [511:0] y); assign y={512{a}}; endmodule'
        r=self.check(ref,ref,total=2)
        self.assertEqual(r['status'],'timeout')
        self.assertIsNone(r['equivalent'])
        self.assertGreater(r['coverage']['proved_bits'],0)
        self.assertLess(r['coverage']['proved_bits'],512)

    def test_state_and_undriven_are_not_proofs(self):
        ref='module top(input a, output y); assign y=a; endmodule'
        variants=['module top(input a, output reg y); always @(posedge a) y=~y; endmodule',
                  'module top(input a, output y); wire z; assign y=z; endmodule']
        for impl in variants:
            self.assertNotEqual(self.check(ref,impl)['status'],'pass')

    def test_dynamic_out_of_range_index_is_not_an_exact_candidate(self):
        ref="module top(input [3:0] a, input [2:0] idx, output y); assign y=idx<4 ? a[idx] : 1'b0; endmodule"
        impl='module top(input [3:0] a, input [2:0] idx, output y); assign y=a[idx]; endmodule'
        r=self.check(ref,impl)
        self.assertNotEqual(r['status'],'pass')
        self.assertIsNot(r['equivalent'],True)

    def test_guarded_dynamic_index_remains_supported(self):
        ref="module top(input [3:0] a, input [2:0] idx, output y); assign y=idx<4 ? a[idx] : 1'b0; endmodule"
        impl="module top(input [3:0] a, input [2:0] idx, output y); assign y=idx[2] ? 1'b0 : a[idx[1:0]]; endmodule"
        self.assertEqual(self.check(ref,impl)['status'],'pass')

    def test_cumulative_lemmas_form_a_proved_prefix(self):
        ref='module top(input [3:0] a,b, output [4:0] y); assign y=a+b; endmodule'
        r=self.check(ref,ref,engine='sat-lemmas')
        self.assertEqual(r['status'],'pass')
        self.assertEqual(r['coverage']['strategy'],'cumulative-proved-lemma-sat')
        for i,bit in enumerate(r['coverage']['bits']):
            self.assertEqual(bit['status'],'pass')
            self.assertEqual(bit['assumed_proved_indices'],list(range(i)))

    def test_cumulative_lemmas_stop_at_first_failure(self):
        ref='module top(input [3:0] a, output [3:0] y); assign y=a; endmodule'
        impl="module top(input [3:0] a, output [3:0] y); assign y=a^4'b0010; endmodule"
        r=self.check(ref,impl,engine='sat-lemmas')
        self.assertEqual(r['status'],'fail')
        self.assertEqual(len(r['coverage']['bits']),2)
        self.assertEqual(r['coverage']['bits'][0]['status'],'pass')
        self.assertEqual(r['coverage']['bits'][1]['status'],'fail')
        self.assertEqual(r['coverage']['bits'][1]['assumed_proved_indices'],[0])

if __name__=='__main__':
    unittest.main(verbosity=2)

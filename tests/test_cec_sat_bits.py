#!/usr/bin/env python3
"""Behavioral regressions: complete bit coverage and last-output mutations."""
import importlib.util,json,sys,tempfile
from pathlib import Path
from support import tool_path
ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/circuit-reverse-rtl/scripts'
sys.path.insert(0,str(SCRIPTS))
from verify import cec,sat_bits
YOSYS=tool_path('yosys')

def check(ref,impl,expected):
 with tempfile.TemporaryDirectory(prefix='sat_bits_test_') as temp:
  work=Path(temp);a=work/'a.v';b=work/'b.v';a.write_text(ref);b.write_text(impl)
  result=cec.run_cec_pair('regression',a,b,YOSYS,Path(''),None,'sat-bits','','z3',10,False,'aiger',10,10,work,True,True,4,1,10,10,2,20)
  assert result.status==expected,(result.status,result.error)
  return result

def main():
 ref='module top(input [3:0] a,b, output [7:0] y, output z); assign y=a*b; assign z=&a; endmodule'
 good=ref.replace('a*b','b*a').replace('&a','a==15')
 assert '9/9' in check(ref,good,'pass').abc_output
 # Every output bit is independently perturbed, including the last bit/port.
 for bit in range(8):
  check(ref,good.replace('b*a',f'(b*a) ^ 8\'d{1<<bit}'),'fail')
 check(ref,good.replace('a==15','a!=15'),'fail')
 # Ascending buses and signed arithmetic retain bit patterns through wrappers.
 signed='module top(input signed [0:3] a,b, output signed [0:7] y); assign y=a*b; endmodule'
 check(signed,signed.replace('a*b','b*a'),'pass')
 check(signed,signed.replace('a*b',"(b*a)^8'd128"),'fail')
 check(ref,good.replace('[7:0] y','[0:7] y'),'interface_mismatch')
 # Declarations in an unused later module must never shrink top's obligation.
 base='module top(a,y); input [3:0] a; output [3:0] y; assign y=a; endmodule'
 extra=' module unused(a,y); input [3:0] a; output y; endmodule'
 check(base+extra,base.replace('y=a','y=a^8')+extra,'fail')
 multidim='module top(input [1:0][3:0] a, output [1:0][3:0] y); assign y=a; endmodule'
 check(multidim,multidim.replace('y=a',"y=a^8'h80"),'interface_error')
 # A local function's argument named like a top port has its own scope.
 function=' function f; input a; begin f=a; end endfunction '
 check(base.replace('endmodule',function+'endmodule'),base.replace('y=a','y=a^8').replace('endmodule',function+'endmodule'),'fail')
 for code,expected in ((124,'timeout'),(130,'error'),(1,'error')):
  assert sat_bits.parse_sat('SAT proof finished - no model found: SUCCESS!',code)==expected
 assert sat_bits.parse_sat('SAT proof finished - model found: FAIL!',0)=='fail'
 assert sat_bits.parse_sat('SAT proof finished - no model found: SUCCESS!\nTIMEOUT',0)=='timeout'
 # A missing proof result is inconclusive even if the process exits normally.
 assert sat_bits.parse_sat('End of script.',0)=='unknown'
 print(json.dumps({'status':'pass','positive_equivalences':2,'output_bit_mutations_rejected':10,'interface_negative':1,'termination_and_missing_result_checks':6}))
import unittest

class SyntheticRegression(unittest.TestCase):
    def test_synthetic_regression(self):
        main()

if __name__=='__main__':main()

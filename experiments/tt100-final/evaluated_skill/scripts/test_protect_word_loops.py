"""Structure controls and complete-domain RTL checks for loop preservation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from truth.protect_word_loops import compact_outside_word_loops
from verify.truth_yosys import verify, default_yosys
YOSYS=default_yosys()

SOURCE='''module top(input [7:0] x, output reg [15:0] y);
  reg signed [63:0] value, count;
  integer i;
  always @(*) begin
    value = 64'sd1 * x - 64'sd128;
    count = 0;
    for (i=0; i<4; i=i+1)
      if (value < 0) begin
        value = value + 1;
        if (value < 0) begin
          count = count - 1;
        end
      end
    y = count + value;
  end
endmodule
'''


def words():
    result=[]
    for x in range(256):
        value,count=x-128,0
        for i in range(4):
            if value<0:
                value+=1
                if value<0:count-=1
        result.append((count+value)&65535)
    return result


def write_truth(path):
    w=words()
    path.write_text('\n'.join(''.join(str((w[255 ^ x]>>b)&1) for x in range(256)) for b in range(16))+'\n')


class ProtectLoopsTests(unittest.TestCase):
    records=[]


    def test_nested_loop_preserved_and_outside_helpers_shared(self):
        changed=compact_outside_word_loops(SOURCE)
        loop=SOURCE[SOURCE.index('    for'):SOURCE.index('    y =')]
        self.assertIn(loop,changed)
        self.assertIn('fp_add(count, value)',changed)
        self.assertNotIn('PRESERVED_WORD_LOOP_',changed)
        self.assertNotEqual(changed,SOURCE)
        self.assertEqual(compact_outside_word_loops(SOURCE.replace('always @(*)','always @*')),SOURCE.replace('always @(*)','always @*'))

    def test_unsupported_and_incomplete_loop_fail_closed(self):
        for mutation in [SOURCE.replace('if (value < 0) begin','if ((value < 0)) begin',1),
                         SOURCE.replace('if (value < 0) begin','begin',1),
                         SOURCE.replace('    y = count + value;','')[:-20],
                         SOURCE.replace('for (i=0; i<4; i=i+1)','for (i=0; i<4; i=i+1) for (i=0; i<4; i=i+1)')]:
            self.assertEqual(compact_outside_word_loops(mutation),mutation)

    def test_full_domain_original_transformed_and_semantic_negative(self):
        with tempfile.TemporaryDirectory() as directory:
            truth=Path(directory)/'input.truth';candidate=Path(directory)/'candidate.v'
            write_truth(truth)
            changed=compact_outside_word_loops(SOURCE)
            negative=changed.replace('count = count - 1;','count = count + 1;')
            self.assertNotEqual(negative,changed)
            for label,source in [('original',SOURCE),('protected',changed),('negative',negative)]:
                candidate.write_text(source)
                result=verify(truth,candidate,YOSYS,use_cache=False,frontend_timeout=120,compile_timeout=120,run_timeout=180,replay_workers=4)
                self.assertEqual(result['frontend'],'pass',(label,result))
                self.assertEqual(result['interface']['status'],'pass',(label,result))
                self.assertEqual(result['status'],'mismatch' if label=='negative' else 'pass',(label,result))
                self.records.append(dict(label=label,result=result))


if __name__=='__main__':
    unittest.main()

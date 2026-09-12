"""Public terminal backend and detached-descendant watchdog controls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/circuit-reverse-rtl/scripts'))
from verify.composition import run_command
CEC=ROOT/'skills/circuit-reverse-rtl/scripts/cec.py'

class TerminalCLI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)
        header='module top(a,b,out); input [6:0] a; input [1:0] b; output [7:0] out;\n'
        lines=[header,'wire '+','.join('c'+str(i) for i in range(7))+';','not g0(out[0],a[0]);','buf c0g(c0,a[0]);']
        for i in range(1,7):lines +=[f'xor s{i}(out[{i}],a[{i}],c{i-1});',f'and c{i}g(c{i},a[{i}],c{i-1});']
        self.ref=self.d/'reference.v';self.cand=self.d/'candidate.v';self.ref.write_text('\n'.join(lines+['buf g7(out[7],c6);','endmodule']))
        self.cand.write_text(header+"assign out={1'b0,a}+8'd1; endmodule\n")
    def tearDown(self):self.tmp.cleanup()
    def check(self,extra=()):
        p=subprocess.run([sys.executable,str(CEC),str(self.ref),str(self.cand),'--engine','algebraic-terminal','--algebraic-coefficient-input','a','--algebraic-timeout','30','--tmpdir',str(self.d/'artifacts'),'--keep-tmp','--json',*extra],capture_output=True,text=True,timeout=45)
        return p,json.loads(p.stdout)
    def test_exact_positive_and_retained_scope(self):
        _,r=self.check();self.assertEqual(r['status'],'pass',r)
        proof=json.loads(next((self.d/'artifacts').glob('*/proof/result.json')).read_text())
        self.assertTrue(proof['strict']);self.assertTrue(proof['all_outputs_compared']);self.assertEqual(proof['original_input_bits'],9)
    def test_last_bit_negative(self):
        self.cand.write_text(self.cand.read_text().replace("+8'd1","+8'd129"));_,r=self.check();self.assertNotEqual(r['status'],'pass')
        command=json.loads(next((self.d/'artifacts').glob('*/proof/coefficient_command.json')).read_text())
        self.assertLessEqual(int(command[command.index('--timeout')+1]),30)
        self.assertGreater(int(command[command.index('--timeout')+1]),0)
        self.assertEqual(command[command.index('--abc-timeout')+1],'60')
    def test_bad_domain(self):
        _,r=self.check(['--algebraic-coefficient-input','missing']);self.assertNotEqual(r['status'],'pass')
    def test_case_split_rejected(self):
        _,r=self.check(['--algebraic-case-split-bit','a[0]']);self.assertNotEqual(r['status'],'pass')
    def test_detached_descendant_stopped(self):
        pidfile=self.d/'pid';script=self.d/'spawn.py'
        script.write_text('import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,"-c","import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"],start_new_session=True)\nPath(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(60)\n')
        try:
            with self.assertRaises(TimeoutError):run_command([sys.executable,str(script),str(pidfile)],self.d/'watchdog',1)
            pid=int(pidfile.read_text());stat=Path(f'/proc/{pid}/stat')
            self.assertTrue(not stat.exists() or stat.read_text().rsplit(')',1)[1].split()[0]=='Z','detached descendant survived timeout')
        finally:
            if pidfile.exists():
                try:os.kill(int(pidfile.read_text()),9)
                except ProcessLookupError:pass

if __name__=='__main__':unittest.main()

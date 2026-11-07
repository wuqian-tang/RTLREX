"""Recovery inference must honor the selected CSV without changing behavior."""
import csv,json,os,random,subprocess,sys,tempfile,unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parent
class ActiveCostRecoveryTest(unittest.TestCase):
 def test_csv_changes_boolean_selection_but_both_remain_exact(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);truth=root/'input.truth';rng=random.Random(913847)
   words=[rng.randrange(8) for _ in range(32)]
   truth.write_text('\n'.join(''.join(str((words[x]>>j)&1) for x in reversed(range(32))) for j in range(3))+'\n')
   original=SCRIPTS/'cost/syntax_cost.csv'
   with original.open() as stream:rows=list(csv.DictReader(stream))
   for r in rows:
    if r['key']=='?:':r['cost']='1000'
    elif r['key'] in ('&','^','~','|'):r['cost']='1'
   custom=root/'custom.csv'
   with custom.open('w',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
   families=[]
   for label,csv_path in [('default',original),('custom',custom)]:
    final=root/(label+'.v')
    command=[sys.executable,'-B',str(SCRIPTS/'recover_truth.py'),str(truth),str(final),'--cost-csv',str(csv_path),'--allow-boolean-fallback','--budget-seconds','60','--engine-timeout','20','--json','--brief']
    result=subprocess.run(command,capture_output=True,text=True,timeout=70,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    self.assertEqual(result.returncode,0,result.stderr+result.stdout)
    report=json.loads(result.stdout);self.assertEqual(report['verification']['status'],'pass');self.assertEqual(report['verification']['vectors'],32)
    families.append(report['family'])
    score=subprocess.run([sys.executable,'-B',str(SCRIPTS/'RTL_cost_calculator.py'),str(final),'--cost-csv',str(csv_path),'--json'],capture_output=True,text=True,check=True)
    self.assertEqual(report['selected_checkpoint']['cost'],json.loads(score.stdout)[0]['cost'])
   self.assertIn('ROBDD',families[0]);self.assertIn('ANF',families[1])
if __name__=='__main__':unittest.main()

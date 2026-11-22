"""Optional all-output exact CEC through bounded PI cones and independent replay.
No cutpoint assumptions and no case assignments are accepted. --timeout bounds
the entire worker process group, including lowering, primary and replay.
"""
import argparse,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
from verify.tooling import resolve_tool
from . import cuts,primary,certificate

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def worker(a):
 start=time.monotonic();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);ref=a.reference.resolve();cand=a.candidate.resolve();result={'status':'unknown','equivalent':None,'strict':False,'engine':'small_pi_cone_algebraic','reference':str(ref),'candidate':str(cand),'cone_input_cap':a.cone_input_cap}
 try:
  assert __debug__,'python -O unsupported';assert 1<=a.cone_input_cap<=8 and a.term_cap>0 and a.timeout>0
  hashes={str(p):sha(p) for p in [ref,cand,*sorted(Path(__file__).parent.glob('*.py'))]}
  item={'input_path':str(ref),'input_sha256':sha(ref),'candidate_path':str(cand),'candidate_sha256':sha(cand)};result.update(reference_sha256=item['input_sha256'],candidate_sha256=item['candidate_sha256'])
  assert certificate.source_contract(ref)==certificate.source_contract(cand),'interface contract mismatch'
  gates,inputs,outputs,constants=certificate.parse_primitive(ref);assert outputs
  ys=resolve_tool('YOSYS',a.yosys);word=out/'candidate_word.json';cmd=[str(ys),'-p',f'read_verilog {cand}; hierarchy -check -top top; proc; opt; check -assert; write_json {word}'];r=subprocess.run(cmd,capture_output=True,text=True,timeout=min(a.timeout,60));(out/'candidate_lower.log').write_text(r.stdout+r.stderr);assert r.returncode==0,'Yosys frontend failed';design=json.loads(word.read_text())['modules']['top']
  ids=cuts.extract(ref);ip=out/'local_identities.json';save(ip,ids);primary_results={}
  for name,bits in outputs.items():
   one={**design,'ports':{n:v for n,v in design['ports'].items() if v['direction']=='input' or n==name}};cp,cinputs=certificate.word_poly(one,len(bits));assert cinputs==inputs and set(cp)=={name};left=a.timeout-(time.monotonic()-start);assert left>0,'time budget exhausted'
   p=primary.reduce_difference_sliced(ref,name,len(bits),cp[name],a.term_cap,left,ids['rewrites'],cone_input_cap=a.cone_input_cap);save(out/(name+'_primary.json'),p);assert p.get('status')=='exact_difference_reduced' and p.get('equivalent') is True,'primary not proved: '+p['status'];primary_results[name]=p
  replay=certificate.verify(item,ip,out/'independent_replay',yosys=ys,term_cap=a.term_cap,sliced_outputs=set(outputs),cone_input_cap=a.cone_input_cap)
  assert replay['all_original_outputs_compared'] and set(replay['outputs'])==set(outputs)
  assert all(sha(p)==h for p,h in hashes.items()),'source changed during proof'
  result.update(status='pass',equivalent=True,strict=True,all_outputs_compared=True,source_hashes=hashes,certificate_path=str(out/'independent_replay/record.json'),certificate_sha256=sha(out/'independent_replay/record.json'),outputs={n:{'bits':len(outputs[n]),'primary_max_terms':p['max_terms'],'replay_max_terms':replay['outputs'][n]['replay_max_terms']} for n,p in primary_results.items()},scope='All original input assignments and all output bits of the hash-bound original source pair; empty-case assumptions only')
 except Exception as e:result.update(reason=type(e).__name__+': '+str(e))
 result['runtime_seconds']=time.monotonic()-start;save(out/'result.json',result);return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--term-cap',type=int,default=300000);p.add_argument('--cone-input-cap',type=int,default=6);p.add_argument('--timeout',type=float,default=120);p.add_argument('--yosys',type=Path);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
 if a.worker:result=worker(a)
 else:
  if a.out.exists():raise FileExistsError(a.out)
  proc=subprocess.Popen([sys.executable,'-m',__package__,*sys.argv[1:],'--worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
  try:
   so,se=proc.communicate(timeout=a.timeout);a.out.mkdir(parents=True,exist_ok=True);(a.out/'worker_stdout.log').write_text(so);(a.out/'worker_stderr.log').write_text(se)
   if proc.returncode!=0 or not (a.out/'result.json').exists():save(a.out/'result.json',{'status':'error','equivalent':None,'strict':False,'reason':'worker failed or exited without result','returncode':proc.returncode})
  except subprocess.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGKILL);so,se=proc.communicate();a.out.mkdir(parents=True,exist_ok=True);(a.out/'worker_stdout.log').write_text(so);(a.out/'worker_stderr.log').write_text(se);save(a.out/'result.json',{'status':'unknown','equivalent':None,'strict':False,'reason':'overall worker process-group timeout','timeout_seconds':a.timeout})
  result=json.loads((a.out/'result.json').read_text())
 print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())

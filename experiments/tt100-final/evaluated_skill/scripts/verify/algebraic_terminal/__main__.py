"""Bounded exact native-terminal residual CEC for one complete output word.
Retain long cones supported by --coefficient-input ports, independently replay
the complete residual, and strictly prove every coefficient against zero.
No case split or assumed internal relation is accepted. The CLI watchdog kills
its complete worker process group on timeout; unsupported inputs stay unknown.
"""
import argparse,hashlib,json,os,signal,shutil,subprocess,sys,time
from pathlib import Path
from . import cuts,primary,certificate,residual,process_control,bdd

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def worker(a):
 start=time.monotonic();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);ref=a.reference.resolve();cand=a.candidate.resolve();result={'status':'unknown','equivalent':None,'strict':False,'all_outputs_compared':False,'engine':'native_terminal_residual','reference':str(ref),'candidate':str(cand)}
 try:
  if not __debug__:raise ValueError('python -O unsupported')
  if not 1<=a.cone_input_cap<=8 or a.term_cap<1 or a.timeout<=0 or a.abc_timeout<=0:raise ValueError('invalid resource limits')
  module=Path(__file__).resolve().parent;root=certificate.ROOT;checker=root/'skills/circuit-reverse-rtl/scripts/verify/cec.py';ys=a.yosys.resolve() if a.yosys else root/'external/yosys/yosys'
  originals=[ref,cand,ys,checker,*sorted(module.glob('*.py'))];hashes={str(p):sha(p) for p in originals};snapshot=out/'checker_sources';snapshot.mkdir()
  for p in module.glob('*.py'):shutil.copyfile(p,snapshot/p.name)
  shutil.copyfile(checker,snapshot/'cec_entrypoint.py')
  item={'input_path':str(ref),'input_sha256':sha(ref),'candidate_path':str(cand),'candidate_sha256':sha(cand)};result.update(reference_sha256=item['input_sha256'],candidate_sha256=item['candidate_sha256'])
  contract=certificate.source_contract(ref)
  if contract!=certificate.source_contract(cand):raise ValueError('interface contract mismatch')
  gates,inputs,outputs,constants=certificate.parse_primitive(ref)
  if len(outputs)!=1:raise ValueError('exactly one complete output word currently supported')
  ports={n for n,d,w,o,s in contract if d=='input'};selected=set(a.coefficient_input)
  if not selected or not selected<=ports or len(selected)!=len(a.coefficient_input):raise ValueError('invalid/duplicate coefficient input port')
  domain={v for v in inputs if v.split('[')[0] in selected};name,bits=next(iter(outputs.items()))
  source_check=[str(ys),'-p',f'read_verilog {ref}; hierarchy -check -top top; proc; check -assert'];checked_source=process_control.run(source_check,timeout=min(a.timeout,60));(out/'reference_syntax.log').write_text(checked_source.stdout+checked_source.stderr)
  if checked_source.returncode:raise ValueError('original reference frontend failed')
  word=out/'candidate_word.json';cmd=[str(ys),'-p',f'read_verilog {cand}; hierarchy -check -top top; proc; opt; check -assert; write_json {word}'];r=process_control.run(cmd,timeout=min(a.timeout,60));(out/'candidate_lower.log').write_text(r.stdout+r.stderr)
  if r.returncode:raise ValueError('Yosys frontend failed')
  design=json.loads(word.read_text())['modules']['top'];cp,cinputs=certificate.word_poly(design,len(bits))
  if cinputs!=inputs or set(cp)!=set(outputs):raise ValueError('candidate polynomial interface mismatch')
  identities=cuts.extract(ref,a.cut_limit);ip=out/'local_identities.json';save(ip,identities)
  remaining=a.timeout-(time.monotonic()-start)
  if remaining<=0:raise TimeoutError('time budget exhausted')
  p=primary.reduce_difference_sliced(ref,name,len(bits),cp[name],a.term_cap,remaining,identities['rewrites'],cone_input_cap=a.cone_input_cap,terminal_inputs=domain);pp=out/'primary_residual.json';save(pp,p)
  if p.get('status')!='terminal_residual_derived':raise ValueError('primary residual incomplete: '+p['status'])
  replay=certificate.verify(item,ip,out/'independent_replay',primary_polynomial=pp,yosys=ys,term_cap=a.term_cap,trim_constant_high_zero=False,sliced_outputs=[name],cone_input_cap=a.cone_input_cap,terminal_inputs=domain)
  if replay['status']!='exact_terminal_residual_replayed' or replay['declared_output_bits']!=len(bits) or replay['polynomial']!=p['polynomial']:raise ValueError('independent residual mismatch')
  audit=residual.construct(ref,out/'independent_replay/record.json',domain,out)
  if audit['coefficient_count'] and a.coefficient_engine=='bdd':
   checked=bdd.prove(ref,out/'coefficient_groups.json',domain,a.bdd_node_cap,a.bdd_order)
   save(out/'coefficient_bdd.json',checked)
   if checked.get('status')!='pass' or checked.get('equivalent') is not True:raise ValueError('BDD coefficient proof incomplete')
  elif audit['coefficient_count']:
   remaining=a.timeout-(time.monotonic()-start)
   if remaining<=0:raise TimeoutError('time budget exhausted before coefficient proof')
   # Yosys lowering can dominate a large coefficient obligation. Its budget is
   # the remaining stage time, independently of the ABC solver's per-call cap.
   # The parent watchdog still bounds this entire nested checker, including both
   # lowerings and ABC, by the same absolute worker deadline.
   command=[sys.executable,str(checker),str(out/'coefficient_reference.v'),str(out/'coefficient_zero.v'),'--engine','cec','--strict-cec','--timeout',str(max(1,int(remaining))),'--abc-timeout',str(a.abc_timeout),'--keep-tmp','--tmpdir',str(out/'coefficient_cec'),'--json'];save(out/'coefficient_command.json',command);r=process_control.run(command,timeout=remaining);(out/'coefficient_stdout.json').write_text(r.stdout);(out/'coefficient_stderr.log').write_text(r.stderr)
   if r.returncode:raise ValueError('coefficient checker nonzero exit')
   checked=json.loads(r.stdout)
   if checked.get('status')!='pass' or checked.get('equivalent') is not True:raise ValueError('not every coefficient proved exactly zero')
   if sha(out/'coefficient_reference.v')!=audit['reference_rtl_sha256'] or sha(out/'coefficient_zero.v')!=audit['zero_rtl_sha256']:raise ValueError('coefficient obligation changed during proof')
  if any(sha(p)!=h for p,h in hashes.items()):raise ValueError('source changed during proof')
  result.update(status='pass',equivalent=True,strict=True,all_outputs_compared=True,source_hashes=hashes,original_input_bits=len(inputs),outputs={name:len(bits)},coefficient_input_ports=sorted(selected),native_terminal_count=p['terminal_count'],residual_terms=p['terms'],coefficient_count=audit['coefficient_count'],coefficient_engine=a.coefficient_engine,certificate_path=str(out/'independent_replay/record.json'),certificate_sha256=sha(out/'independent_replay/record.json'),scope='All original primary input assignments and every bit of the single complete original output; retained native gate functions are independently discharged, not assumed cutpoint relations.')
 except Exception as e:result.update(reason=type(e).__name__+': '+str(e))
 result['runtime_seconds']=time.monotonic()-start;save(out/'result.json',result);return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--coefficient-input',action='append',required=True,help='original input port whose bits may support retained native terminals; repeat for a union of ports');p.add_argument('--term-cap',type=int,default=300000);p.add_argument('--cone-input-cap',type=int,default=6);p.add_argument('--cut-limit',type=int,default=48);p.add_argument('--timeout',type=float,default=180);p.add_argument('--abc-timeout',type=int,default=60);p.add_argument('--coefficient-engine',choices=['cec','bdd'],default='cec');p.add_argument('--bdd-node-cap',type=int,default=1000000);p.add_argument('--bdd-order',choices=['bit-major','port-major'],default='bit-major');p.add_argument('--yosys',type=Path);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
 if a.worker:result=worker(a)
 else:
  if a.out.exists():raise FileExistsError(a.out)
  proc=subprocess.Popen([sys.executable,'-m',__package__,*sys.argv[1:],'--worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
  try:
   so,se=proc.communicate(timeout=a.timeout);a.out.mkdir(parents=True,exist_ok=True);(a.out/'worker_stdout.log').write_text(so);(a.out/'worker_stderr.log').write_text(se)
   if proc.returncode!=0 or not (a.out/'result.json').exists():save(a.out/'result.json',{'status':'error','equivalent':None,'strict':False,'all_outputs_compared':False,'reason':'worker failed or exited without result','returncode':proc.returncode})
  except subprocess.TimeoutExpired:
   killed=process_control.stop_tree(proc);so,se=proc.communicate();a.out.mkdir(parents=True,exist_ok=True);(a.out/'worker_stdout.log').write_text(so);(a.out/'worker_stderr.log').write_text(se);save(a.out/'result.json',{'status':'unknown','equivalent':None,'strict':False,'all_outputs_compared':False,'reason':'overall worker process-group timeout','timeout_seconds':a.timeout,'cancelled_descendant_pids':killed})
  result=json.loads((a.out/'result.json').read_text())
 print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())

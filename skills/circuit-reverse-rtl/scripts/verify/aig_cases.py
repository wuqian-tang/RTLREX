#!/usr/bin/env python3
"""Exact exhaustive primary-input cofactors for a complete 2-state AIG pair.

Checks AIG pairs only. A caller claiming original RTL equivalence must separately
prove and archive complete original-RTL/AIG interface bridges. No guessed tap or
source-language assumption is admitted here. Replay audits archived solver logs
and independently checks every cofactor; it is explicitly not a fresh solver run.
"""
from pathlib import Path
import argparse,concurrent.futures,json,os,re,signal,subprocess,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify.tooling import resolve_tool, artifact_path, load_plan
from verify.composition import read_aig,sha


def require(ok,message):
 if not ok:raise ValueError(message)
def save(path,obj):Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
def artifact(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}
def checked_artifact(item):
 require(isinstance(item,dict) and set(item)=={'path','sha256'},'invalid artifact record');p=Path(item['path']);require(p.is_file() and sha(p)==item['sha256'],'artifact missing or changed');return p

def cofactor(graph,path,assignments):
 """Primary implementation: forward propagation and structural hashing."""
 pairs=[];intern={};mapping={0:0}
 for i in range(graph['I']):mapping[i+1]=assignments.get(i,2*(i+1))
 def literal(value):return mapping[value>>1]^(value&1)
 for n,(a,b) in enumerate(graph['gates'],graph['I']+1):
  a,b=literal(a),literal(b)
  if not a or not b or a==(b^1):z=0
  elif a==1:z=b
  elif b==1 or a==b:z=a
  else:
   key=tuple(sorted((a,b),reverse=True));z=intern.get(key)
   if z is None:z=2*(graph['I']+len(pairs)+1);pairs.append(key);intern[key]=z
  mapping[n]=z
 outputs=[literal(x) for x in graph['outputs']]
 def encode(v):
  result=bytearray()
  while v>127:result.append((v&127)|128);v>>=7
  result.append(v);return result
 data=bytearray(f'aig {graph["I"]+len(pairs)} {graph["I"]} 0 {len(outputs)} {len(pairs)}\n'.encode());data.extend(('\n'.join(map(str,outputs))+'\n').encode())
 for n,(a,b) in enumerate(pairs,graph['I']+1):data.extend(encode(2*n-a));data.extend(encode(a-b))
 for kind in ['i','o']:
  for i,name in graph['symbols'][kind].items():data.extend(f'{kind}{i} {name}\n'.encode())
 Path(path).write_bytes(data)

def canonical(graph,assigned,table):
 """Independent inductive Boolean DAG audit, sharing only the AIG reader."""
 nodes=[0]
 def intern(key):
  if key not in table:table[key]=2*(len(table)+1)
  return table[key]
 for i in range(graph['I']):nodes.append(assigned[i] if i in assigned else intern(('input',graph['symbols']['i'][i])))
 def edge(e):return nodes[e//2]^(e%2)
 for a,b in graph['gates']:
  x,y=edge(a),edge(b)
  if x==0 or y==0 or x==(y^1):z=0
  elif x==1:z=y
  elif y==1 or x==y:z=x
  else:z=intern(('and',min(x,y),max(x,y)))
  nodes.append(z)
 return tuple(edge(e) for e in graph['outputs'])

def audit_cofactor(original,derived,assignments):
 require(original['symbols']==derived['symbols'],'cofactor changed complete interface');table={}
 require(canonical(original,assignments,table)==canonical(derived,{},table),'independent cofactor identity failed')

def solver_pass(log,returncode):
 if type(returncode) is not int or returncode!=0:return False
 if re.search(r'NOT EQUIVALENT|Verification failed|\b[Tt]imeout\b|\b[Ee]rror\b',log):return False
 return re.search(r'^Networks are equivalent(?:\.| after structural hashing\.)',log,re.M) is not None

def prove(args):
 start=time.monotonic();out=args.out.resolve();out.mkdir(exist_ok=False);sources=[args.reference_aig.resolve(),args.candidate_aig.resolve()];pins=[artifact(p) for p in sources];graphs=[read_aig(p) for p in sources];result={'status':'unknown','strict':False,'equivalent':None,'scope':'complete supplied AIG pair only; original RTL bindings are separate obligations'}
 try:
  require(graphs[0]['symbols']==graphs[1]['symbols'],'full AIG input/output symbols differ');names=list(args.split_input);require(1<=len(names)<=12 and len(set(names))==len(names),'one to twelve distinct complete input symbols required');indices={n:i for i,n in graphs[0]['symbols']['i'].items()};require(all(n in indices for n in names),'split names must be existing primary-input symbols');count=1<<len(names);require(1<=args.jobs<=16 and args.branch_timeout>0 and args.timeout>0,'invalid resource limits');checker_pin=sha(__file__);parser_pin=sha(Path(__file__).with_name('composition.py'));rows=[]
  def assignment(i):return {indices[n]:(i>>b)&1 for b,n in enumerate(names)}
  if args.replay_manifest:
   manifest=load_plan(args.replay_manifest);require(manifest.get('schema')=='aig-cases/v1','invalid replay schema');require(manifest['split_inputs']==names,'replay split ordering changed')
   for old,current in zip([manifest['reference_aig'],manifest['candidate_aig']],pins):require(checked_artifact(old).read_bytes()==Path(current['path']).read_bytes(),'replay source pair differs')
   archived=manifest['branches'];require(len(archived)==count and sorted(r['index'] for r in archived)==list(range(count)),'missing or duplicate cube: exhaustive coverage required')
   for row in sorted(archived,key=lambda r:r['index']):
    i=row['index'];require(type(i) is int,'invalid cube index')
    for g,key in zip(graphs,['reference','candidate']):audit_cofactor(g,read_aig(checked_artifact(row[key])),assignment(i))
    log=checked_artifact(row['solver_log']).read_text();require(solver_pass(log,row['returncode']),'archived solver did not strictly prove this cube');rows.append(row)
   mode='archived_solver_replay_with_fresh_independent_cofactor_audit'
  else:
   abc=resolve_tool('ABC',args.abc);require(abc.is_file(),'ABC executable missing');abc_pin=artifact(abc)
   def branch(i):
    folder=out/f'cube_{i}';folder.mkdir();fixed=assignment(i);paths=[folder/'reference.aig',folder/'candidate.aig']
    for graph,path in zip(graphs,paths):cofactor(graph,path,fixed);audit_cofactor(graph,read_aig(path),fixed)
    cmd=[str(abc),'-c','cec reference.aig candidate.aig'];p=subprocess.Popen(cmd,cwd=folder,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:so,se=p.communicate(timeout=args.branch_timeout);rc=p.returncode
    except subprocess.TimeoutExpired:p.kill();so,se=p.communicate();rc=None;se+='\nTimeout: branch budget exhausted\n'
    log=folder/'solver.log';log.write_text(so+se);row={'index':i,'reference':artifact(paths[0]),'candidate':artifact(paths[1]),'solver_log':artifact(log),'returncode':rc,'strict_pass':solver_pass(so+se,rc)};save(folder/'result.json',row);return row
   with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
    for row in pool.map(branch,range(count)):rows.append(row)
   require(all(row['strict_pass'] for row in rows),'at least one cube failed or was not strictly proved');require(sha(abc)==abc_pin['sha256'],'ABC changed during proof');mode='fresh_solver_run'
  require(all(sha(p)==a['sha256'] for p,a in zip(sources,pins)),'source changed during proof');require(sha(__file__)==checker_pin and sha(Path(__file__).with_name('composition.py'))==parser_pin,'checker changed during proof')
  archive={'schema':'aig-cases/v1','reference_aig':pins[0],'candidate_aig':pins[1],'split_inputs':names,'branches':rows};save(out/'archive.json',archive);result.update(status='pass',strict=True,equivalent=True,all_original_inputs_free=True,all_original_output_bits_compared=graphs[0]['O'],original_input_bits=graphs[0]['I'],cubes=count,execution_mode=mode,source_aigs=pins,checker_sha256=checker_pin,aig_reader_sha256=parser_pin,archive=artifact(out/'archive.json'))
 except Exception as e:result['reason']=type(e).__name__+': '+str(e)
 result['runtime_seconds']=time.monotonic()-start;save(out/'result.json',result);return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference-aig',type=Path,required=True);p.add_argument('--candidate-aig',type=Path,required=True);p.add_argument('--split-input',action='append',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--replay-manifest',type=Path);p.add_argument('--abc',type=Path);p.add_argument('--jobs',type=int,default=4);p.add_argument('--branch-timeout',type=float,default=30);p.add_argument('--timeout',type=float,default=900);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
 if a.worker:result=prove(a)
 else:
  require(not a.out.exists(),'output directory already exists');require(a.timeout>0,'positive whole-proof timeout required');a.out.parent.mkdir(parents=True,exist_ok=True)
  worker=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
  try:
   so,se=worker.communicate(timeout=a.timeout)
   if worker.returncode!=0 or not (a.out/'result.json').exists():
    a.out.mkdir(exist_ok=True);save(a.out/'result.json',{'status':'error','strict':False,'equivalent':None,'reason':'worker exited without a valid result','returncode':worker.returncode})
  except subprocess.TimeoutExpired:
   os.killpg(worker.pid,signal.SIGKILL);so,se=worker.communicate();a.out.mkdir(exist_ok=True);save(a.out/'result.json',{'status':'unknown','strict':False,'equivalent':None,'reason':'complete worker process-group timeout','timeout_seconds':a.timeout})
  (a.out/'worker_stdout.log').write_text(so);(a.out/'worker_stderr.log').write_text(se);result=json.loads((a.out/'result.json').read_text())
 print(json.dumps(result,sort_keys=True));return 0 if a.worker or result.get('strict') is True else 1
if __name__=='__main__':raise SystemExit(main())

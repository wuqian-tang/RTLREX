#!/usr/bin/env python3
"""Bounded full-output algebraic CEC; unsupported constructs return unknown.
Use `python -m verify.algebraic --reference REF --candidate RTL --out DIR`.
The caller should enforce a process-group timeout; --timeout also bounds each
primary polynomial reduction. No simulation result is accepted as a proof.
"""
import argparse,contextlib,hashlib,io,itertools,json,shutil,subprocess,sys,time
from pathlib import Path
from . import certificate,cuts,polynomial

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def main():
 if not __debug__:raise RuntimeError('python -O is not supported for certification')
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--term-cap',type=int,default=100000);p.add_argument('--timeout',type=float,default=120);p.add_argument('--yosys',type=Path);p.add_argument('--cut-limit',type=int,default=48);p.add_argument('--sliced-output',action='append',default=[],help='prove this output as a significance-sliced reference-minus-candidate identity; repeat for multiple outputs');p.add_argument('--case-split-bit',action='append',default=[],help='exhaustively split an algebraic proof on this named primary-input bit; repeat for multiple bits');a=p.parse_args()
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();captured=io.StringIO()
 result={'status':'unknown','equivalent':None,'engine':'verified_boolean_polynomial','strict':False,'reference':str(a.reference.resolve()),'candidate':str(a.candidate.resolve())}
 try:
  if a.term_cap<1 or a.timeout<=0 or a.cut_limit<1:raise ValueError('resource limits must be positive')
  reference=a.reference.resolve();candidate=a.candidate.resolve();module=Path(__file__).resolve().parent
  yosys=a.yosys or (module.parents[4]/'external/yosys/yosys')
  if not yosys.exists():yosys=Path(shutil.which('yosys') or '')
  if not yosys.is_file():raise ValueError('Yosys executable unavailable; pass --yosys')
  result.update(reference_sha256=sha(reference),candidate_sha256=sha(candidate),yosys_path=str(yosys.resolve()),yosys_sha256=sha(yosys))
  item={'input_path':str(reference),'input_sha256':sha(reference),'candidate_path':str(candidate),'candidate_sha256':sha(candidate)}
  if certificate.source_contract(reference)!=certificate.source_contract(candidate):raise ValueError('input/output interface contracts differ')
  gates,inputs,outputs,constants=certificate.parse_primitive(reference)
  if not outputs:raise ValueError('at least one output is required')
  sliced_outputs=set(a.sliced_output)
  if not sliced_outputs<=set(outputs):raise ValueError('unknown --sliced-output: '+','.join(sorted(sliced_outputs-set(outputs))))
  case_bits=list(a.case_split_bit)
  if len(case_bits)!=len(set(case_bits)):raise ValueError('duplicate --case-split-bit')
  if not set(case_bits)<=inputs:raise ValueError('case-split bits must be original primary-input bits: '+','.join(sorted(set(case_bits)-inputs)))
  if len(case_bits)>8:raise ValueError('at most eight case-split bits are supported')
  if case_bits and sliced_outputs!=set(outputs):raise ValueError('case-split mode requires every output to use --sliced-output')
  case_assignments=[dict(zip(case_bits,values)) for values in itertools.product([0,1],repeat=len(case_bits))]
  # Primary reduction can discard only syntactically/provably constant-zero
  # high outputs. Independent replay re-establishes these constants separately.
  constant_cache={};constant_active=set()
  def constant_value(n):
   if n in constants:return constants[n]
   if n in constant_cache:return constant_cache[n]
   if n not in gates:return None
   if n in constant_active:raise ValueError('reference constant-cone cycle')
   constant_active.add(n);op,aa=gates[n];values=[constant_value(v) for v in aa]
   if any(v is None for v in values):value=None
   elif op=='buf':value=values[0]
   elif op=='not':value=1-values[0]
   elif op in ['and','nand']:value=int(all(values));value=1-value if op=='nand' else value
   elif op in ['or','nor']:value=int(any(values));value=1-value if op=='nor' else value
   else:value=sum(values)%2;value=1-value if op=='xnor' else value
   constant_active.remove(n);constant_cache[n]=value;return value
  effective_widths={}
  for name,bits in outputs.items():
   width=len(bits)
   while width>1 and constant_value(bits[width-1])==0:width-=1
   effective_widths[name]=width
  targets={}
  if sliced_outputs:
   wordjson=out/'primary_candidate_word.json';command=[str(yosys),'-p',f'read_verilog {candidate}; hierarchy -check -top top; proc; opt; check -assert; write_json {wordjson}']
   process=subprocess.run(command,cwd=module.parents[4],capture_output=True,text=True,timeout=60);(out/'primary_candidate_lower.log').write_text(process.stdout+process.stderr)
   if process.returncode!=0:raise ValueError('candidate word-level lowering failed')
   design=json.loads(wordjson.read_text())['modules']['top']
   for name in sliced_outputs:
    declared_width=len(outputs[name]);single={**design,'ports':{n:p for n,p in design['ports'].items() if p['direction']=='input' or n==name}}
    candidate_polynomials,candidate_inputs=certificate.word_poly(single,declared_width)
    if candidate_inputs!=inputs or set(candidate_polynomials)!={name}:raise ValueError('candidate sliced-output interface mismatch')
    mod=1<<effective_widths[name];targets[name]={t:c%mod for t,c in candidate_polynomials[name].items() if c%mod}
   save(out/'sliced_targets.json',{'candidate':str(candidate),'candidate_sha256':sha(candidate),'outputs':{name:[{'variables':sorted(term),'coefficient':coefficient} for term,coefficient in sorted(target.items(),key=lambda item:(len(item[0]),sorted(item[0])))] for name,target in sorted(targets.items())}})
  with contextlib.redirect_stdout(captured):
   identities=cuts.extract(reference,a.cut_limit);ip=out/'local_identities.json';save(ip,identities)
   primary={}
   for name,bits in outputs.items():
    remaining=a.timeout-(time.monotonic()-start)
    if remaining<=0:raise TimeoutError('algebraic time limit')
    if name in sliced_outputs:
     if case_bits:
      branches=[]
      for index,assignment in enumerate(case_assignments):
       remaining=a.timeout-(time.monotonic()-start)
       if remaining<=0:raise TimeoutError('algebraic time limit')
       mod=1<<effective_widths[name];restricted={}
       for term,coefficient in targets[name].items():
        if any(bit in term and not assignment[bit] for bit in case_bits):continue
        reduced=term-set(case_bits);restricted[reduced]=(restricted.get(reduced,0)+coefficient)%mod
        if not restricted[reduced]:del restricted[reduced]
       branch=polynomial.reduce_difference_sliced(reference,name,effective_widths[name],restricted,a.term_cap,remaining,identities['rewrites'],assignment)
       branch_path=out/f'{name}_case_{index:0{max(1,len(case_bits))}b}_primary_polynomial.json';save(branch_path,branch)
       if branch['status']!='exact_difference_reduced' or not branch['equivalent']:raise ValueError('primary case-split branch did not prove equality: '+branch['status'])
       branches.append({'assignment':assignment,'path':str(branch_path),'status':branch['status'],'equivalent':branch['equivalent'],'max_terms':branch['max_terms'],'runtime_seconds':branch['runtime_seconds']})
      r={'status':'exact_exhaustive_case_split','equivalent':True,'source_sha256':sha(reference),'output':name,'width':effective_widths[name],'case_split_bits':case_bits,'complete_boolean_cube':True,'branch_count':len(branches),'branches':branches,'polynomial':[],'max_terms':max(x['max_terms'] for x in branches),'runtime_seconds':sum(x['runtime_seconds'] for x in branches)};save(out/(name+'_primary_polynomial.json'),r)
     else:
      r=polynomial.reduce_difference_sliced(reference,name,effective_widths[name],targets[name],a.term_cap,remaining,identities['rewrites'])
      save(out/(name+'_primary_polynomial.json'),r)
      if r['status']!='exact_difference_reduced' or not r['equivalent']:raise ValueError('primary sliced reduction did not prove equality: '+r['status'])
    else:
     r=polynomial.reduce(reference,name,effective_widths[name],a.term_cap,remaining,identities['rewrites'])
     save(out/(name+'_primary_polynomial.json'),r)
     if r['status']!='exact_polynomial_derived':raise ValueError('primary reduction did not finish: '+r['status'])
    primary[name]=r
   replay=certificate.verify(item,ip,out/'independent_replay',yosys=yosys,term_cap=a.term_cap,sliced_outputs=sliced_outputs,case_splits=case_assignments if case_bits else None)
  for name,r in primary.items():
   if case_bits:
    if r['status']!='exact_exhaustive_case_split' or not replay['outputs'][name]['case_split_complete_boolean_cube']:raise ValueError('independent case-split replay differs')
    if [x['assignment'] for x in r['branches']]!=[x['assignment'] for x in replay['outputs'][name]['case_split_branches']]:raise ValueError('independent case-split assignments differ')
   else:
    lhs={frozenset(x['variables']):x['coefficient'] for x in r['polynomial']};rhs={frozenset(x['variables']):x['coefficient'] for x in replay['outputs'][name]['polynomial']}
    if lhs!=rhs:raise ValueError('independent polynomial replay differs')
  if not replay['all_original_outputs_compared']:raise ValueError('incomplete output coverage')
  if sha(reference)!=item['input_sha256'] or sha(candidate)!=item['candidate_sha256']:raise ValueError('input file changed during proof')
  result.update(status='pass',equivalent=True,strict=True,all_outputs_compared=True,sliced_outputs=sorted(sliced_outputs),case_split_bits=case_bits,case_split_complete_boolean_cube=bool(case_bits),outputs={n:{k:v for k,v in r.items() if k!='polynomial'} for n,r in replay['outputs'].items()},local_identities=replay['local_identities'],local_exhaustive_assignments=replay['local_exhaustive_assignments'],certificate_path=str(out/'independent_replay/record.json'))
 except (AssertionError,ValueError,TimeoutError,RecursionError,KeyError) as exc:
  result.update(status='unknown',equivalent=None,strict=False,reason=f'{type(exc).__name__}: {exc}')
 except Exception as exc:
  result.update(status='error',equivalent=None,strict=False,reason=f'{type(exc).__name__}: {exc}')
 (out/'trace.log').write_text(captured.getvalue());result['runtime_seconds']=time.monotonic()-start
 result['module_sha256']={str(q.name):sha(q) for q in sorted(Path(__file__).resolve().parent.glob('*.py'))}
 save(out/'result.json',result);print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':sys.exit(main())

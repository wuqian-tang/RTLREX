#!/usr/bin/env python3
"""Independently replay a primitive-network polynomial certificate.
Checks local cuts by exhaustive evaluation of the ORIGINAL gates, then redoes
all substitutions with a separate simple polynomial implementation. Candidate
polynomials are derived from Yosys word cells, not benchmark-specific formulas.
Supported candidate cells: unsigned add/sub/mul and scalar mux.  A mux control
may be a primary bit or a small, exhaustively lowered two-state Boolean cell.
Cell outputs must be at the compared width or have a proved structural unsigned
range bound that justifies lifting a narrower result. Wiring may zero-extend
primary bits or left-shift/truncate a full-width internal word modulo 2**W.
Other cases reject.
"""
import argparse,hashlib,itertools,json,re,subprocess,time
from pathlib import Path
from verify.tooling import resolve_tool, artifact_path
HERE=Path(__file__).resolve().parent
if not __debug__:raise RuntimeError('Certification requires Python assertions enabled; python -O is rejected')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def source_contract(path):
 text=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(),flags=re.S)
 assert len(re.findall(r'\bmodule\b',text))==1 and len(re.findall(r'\bendmodule\b',text))==1
 header=re.search(r'\bmodule\s+top\s*\(([^()]*)\)\s*;',text);assert header,'only explicit non-ANSI top interface supported'
 names=[n.strip() for n in header[1].split(',')];assert len(names)==len(set(names)) and all(re.fullmatch(r'\w+',n) for n in names)
 declarations={}
 for stmt in text.split(';'):
  st=stmt.strip()
  if not re.match(r'^(input|output)\b',st):continue
  d=re.fullmatch(r'(input|output)\s*(?:\[(\d+)\s*:\s*(\d+)\]\s*)?(.+)',st);assert d,'signed, ANSI, or unsupported port declaration'
  hi=int(d[2] or 0);lo=int(d[3] or 0);assert lo==0 and hi>=lo,'ascending/nonzero-offset ports unsupported'
  for n in d[4].split(','):
   n=n.strip();assert re.fullmatch(r'\w+',n) and n not in declarations
   declarations[n]=(d[1],hi+1,lo,False)
 assert set(names)==set(declarations),'incomplete or extra declared ports'
 return [(n,*declarations[n]) for n in names]

def parse_primitive(path):
 text=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(),flags=re.S);gates={};inputs=set();outputs={}
 assert len(re.findall(r'\bmodule\b',text))==1 and len(re.findall(r'\bendmodule\b',text))==1
 for statement in text.split(';'):
  s=statement.strip()
  if not s or s=='endmodule' or re.match(r'^module\b',s) or re.match(r'^wire\b',s):continue
  m=re.fullmatch(r'(input|output)\s*(?:\[(\d+)\s*:\s*(\d+)\]\s*)?(.+)',s)
  if m:
   scalar=m[2] is None;hi=int(m[2] or 0);lo=int(m[3] or 0);assert lo==0 and hi>=lo
   for n in m[4].split(','):
    n=n.strip();assert re.fullmatch(r'\w+',n)
    bits=[n] if scalar else [f'{n}[{b}]' for b in range(hi+1)]
    if m[1]=='input':inputs.update(bits)
    else:outputs[n]=bits
   continue
  m=re.fullmatch(r'(and|nand|or|nor|xor|xnor|not|buf)\s+\w+\s*\(([^()]*)\)',s)
  if not m:raise ValueError('unsupported primitive source statement: '+s[:100])
  aa=[re.sub(r'\s+','',x) for x in m[2].split(',')];assert aa[0] not in gates and aa[0] not in inputs
  assert len(aa)==2 if m[1] in ['not','buf'] else len(aa)>=3
  gates[aa[0]]=(m[1],aa[1:])
 constants={"1'b0":0,"1'b1":1,"1'd0":0,"1'd1":1,"1'h0":0,"1'h1":1,'0':0,'1':1}
 for op,aa in gates.values():assert all(n in inputs or n in gates or n in constants for n in aa),'undriven/unknown gate input'
 assert all(n in gates or n in inputs for bb in outputs.values() for n in bb),'undriven output'
 return gates,inputs,outputs,constants

def word_poly(design,width,bound_records=None,condition_records=None,output_bounds=None):
 if any(int(c.get('parameters',{}).get(k,'0'),2) for c in design['cells'].values() for k in ['A_SIGNED','B_SIGNED']):
  from .word_signed import word_poly_signed
  return word_poly_signed(design,width,bound_records,output_bounds)
 mod=1<<width;ports=design['ports'];primary={};drivers={}
 for n,p in ports.items():
  assert p.get('offset',0)==0 and not p.get('upto',0) and not p.get('signed',0),'nonzero-offset/ascending/signed port unsupported'
  if p['direction']=='input':
   assert p.get('offset',0)==0 and not p.get('upto',0)
   for b,v in enumerate(p['bits']):primary[v]=n if len(p['bits'])==1 else f'{n}[{b}]'
 for n,c in design['cells'].items():
  if 'Y' not in c.get('connections',{}):continue
  key=tuple(c['connections']['Y']);assert key not in drivers;drivers[key]=c
 def add(a,b,factor=1):
  z=a.copy()
  for t,c in b.items():
   z[t]=(z.get(t,0)+factor*c)%mod
   if not z[t]:del z[t]
  return z
 def scale(a,k):return {t:c*k%mod for t,c in a.items() if c*k%mod}
 def mul(a,b):
  z={}
  for x,c in a.items():
   for y,d in b.items():
    t=x|y;z[t]=(z.get(t,0)+c*d)%mod
    if not z[t]:del z[t]
  return z
 memo={};bounds={};active=set();condition_memo={};condition_active=set()
 def parameter(c,name):return int(c.get('parameters',{}).get(name,'0'),2)
 def direct_bit(v,assignment=None):
  if v=='0':return 0
  if v=='1':return 1
  assert v in primary,'Boolean condition depends on an unsupported internal bit'
  return assignment[primary[v]] if assignment is not None else {frozenset([primary[v]]):1}
 def condition(bits):
  """Return an exact 0/1 multilinear polynomial for a scalar selector."""
  key=tuple(bits);assert len(key)==1,'only scalar mux controls supported'
  if key in condition_memo:return condition_memo[key]
  v=key[0]
  if v in ['0','1'] or v in primary:
   z={} if v=='0' else ({frozenset():1} if v=='1' else {frozenset([primary[v]]):1})
   condition_memo[key]=z;return z
  assert key not in condition_active,'candidate condition cycle';condition_active.add(key)
  assert key in drivers,'undriven/unsupported scalar mux control'
  c=drivers[key];co=c['connections'];kind=c['type']
  binary={'$eq','$ne','$lt','$le','$gt','$ge','$logic_and','$logic_or','$and','$or','$xor','$xnor'}
  unary={'$logic_not','$reduce_bool','$reduce_or','$reduce_and','$reduce_xor','$reduce_xnor','$not'}
  assert kind in binary|unary,('unsupported scalar condition cell',kind)
  assert len(co['Y'])==parameter(c,'Y_WIDTH')==1,'condition cell must have one output bit'
  assert parameter(c,'A_SIGNED')==0 and (kind not in binary or parameter(c,'B_SIGNED')==0),'signed condition requires separate proof'
  operands=[co['A']]+([co['B']] if kind in binary else [])
  assert all(v in primary or v in ['0','1'] for operand in operands for v in operand),'condition operands must be primary bits or constants'
  variables=sorted({primary[v] for operand in operands for v in operand if v in primary})
  assert len(variables)<=8,'condition support exceeds exhaustive lowering limit'
  def value(bits,assignment):return sum(direct_bit(v,assignment)<<b for b,v in enumerate(bits))
  def evaluate(assignment):
   a=value(co['A'],assignment);b=value(co['B'],assignment) if kind in binary else None
   if kind=='$eq':return int(a==b)
   if kind=='$ne':return int(a!=b)
   if kind=='$lt':return int(a<b)
   if kind=='$le':return int(a<=b)
   if kind=='$gt':return int(a>b)
   if kind=='$ge':return int(a>=b)
   if kind=='$logic_not':return int(a==0)
   if kind=='$logic_and':return int(a!=0 and b!=0)
   if kind=='$logic_or':return int(a!=0 or b!=0)
   if kind in ['$reduce_bool','$reduce_or']:return int(a!=0)
   if kind=='$reduce_and':return int(a==(1<<len(co['A']))-1)
   if kind=='$reduce_xor':return a.bit_count()&1
   if kind=='$reduce_xnor':return 1-(a.bit_count()&1)
   if kind=='$not':return (~a)&1
   if kind=='$and':return (a&b)&1
   if kind=='$or':return (a|b)&1
   if kind=='$xor':return (a^b)&1
   if kind=='$xnor':return (~(a^b))&1
   raise AssertionError('unreachable condition kind')
  table=[]
  for mask in range(1<<len(variables)):
   assignment={name:(mask>>i)&1 for i,name in enumerate(variables)}
   table.append(evaluate(assignment))
  coefficients=table.copy()
  for i in range(len(variables)):
   for mask in range(1<<len(variables)):
    if mask&(1<<i):coefficients[mask]-=coefficients[mask^(1<<i)]
  z={frozenset(variables[i] for i in range(len(variables)) if mask&(1<<i)):coefficient%mod for mask,coefficient in enumerate(coefficients) if coefficient%mod}
  for mask,expected in enumerate(table):
   assignment={name:(mask>>i)&1 for i,name in enumerate(variables)}
   actual=sum(coefficient*all(assignment[name] for name in term) for term,coefficient in z.items())%mod
   assert actual==expected
  if condition_records is not None:
   condition_records.append({'cell_type':kind,'support':variables,'assignments_checked':len(table),'truth_table':table,'multilinear_terms':[{'variables':sorted(term),'coefficient_modulo_ring':coefficient} for term,coefficient in sorted(z.items(),key=lambda x:(len(x[0]),sorted(x[0])))]})
  condition_active.remove(key);condition_memo[key]=z;return z
 def bus(bits):
  key=tuple(bits)
  if key in memo:return memo[key]
  assert key not in active,'candidate combinational cycle';active.add(key)
  if all(v in primary or v in ['0','1'] for v in bits):
   z={}
   for b,v in enumerate(bits):
    if v=='0':continue
    z=add(z,{frozenset() if v=='1' else frozenset([primary[v]]):1<<b})
   upper=sum(1<<b for b,v in enumerate(bits) if v!='0')
  elif key in drivers:
   c=drivers[key];co=c['connections'];assert c['type'] in ['$add','$sub','$mul','$mux'],('unsupported cell',c['type'])
   assert 0<len(co['Y'])<=width,'wider internal result unsupported'
   assert all(parameter(c,k)==0 for k in ['A_SIGNED','B_SIGNED']),'signed cell requires separate proof'
   a=bus(co['A']);b=bus(co['B'])
   au=bounds[tuple(co['A'])];bu=bounds[tuple(co['B'])]
   if c['type']=='$add':z=add(a,b);raw_upper=au+bu
   elif c['type']=='$sub':z=add(a,b,-1);raw_upper=None
   elif c['type']=='$mul':z=mul(a,b);raw_upper=au*bu
   else:
    select=condition(co['S']);z=add(a,mul(select,add(b,a,-1)));raw_upper=max(au,bu)
   cell_width=len(co['Y'])
   if cell_width<width:
    assert raw_upper is not None and raw_upper<(1<<cell_width),'narrow result upper-bound certificate insufficient'
    upper=raw_upper
    if bound_records is not None:bound_records.append({'cell_type':c['type'],'native_width':cell_width,'comparison_ring_width':width,'structural_unsigned_upper_bound_inclusive':upper,'native_unsigned_value_bound_exclusive':1<<cell_width})
   else:upper=min(raw_upper,mod-1) if raw_upper is not None else mod-1
  else:
   # Exact modular wiring rule: (Y mod 2**(W-k))*2**k == Y*2**k mod 2**W.
   assert len(bits)==width,'unsupported partial internal bus'
   matches=[(y,k) for y in drivers for k in range(width) if bits==['0']*k+list(y[:width-k])+['0']*max(0,width-k-len(y))]
   if not matches:raise ValueError('unsupported internal slice/extension')
   y,k=matches[0];z=scale(bus(y),1<<k);upper=min(bounds[y],(1<<(width-k))-1)*(1<<k)
  active.remove(key);memo[key]=z;bounds[key]=upper;return z
 result={n:bus(p['bits']) for n,p in ports.items() if p['direction']=='output'}
 if output_bounds is not None:output_bounds.update({n:bounds[tuple(p['bits'])] for n,p in ports.items() if p['direction']=='output'})
 return result,set(primary.values())

def verify(item,identities_path,out,primary_polynomial=None,yosys=None,term_cap=100000,trim_constant_high_zero=True,optimize_word=True,sliced_outputs=None,case_splits=None,cone_input_cap=6,base_dir=None):
 assert 1<=cone_input_cap<=8,'cone input cap must be 1..8'
 assert not case_splits or case_splits==[{}],'small-PI backend rejects case-split assumptions'
 identities_path=artifact_path(identities_path,base_dir);primary_polynomial=artifact_path(primary_polynomial,base_dir) if primary_polynomial is not None else None
 start=time.monotonic();yosys=resolve_tool('YOSYS',yosys);out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);source=artifact_path(item['input_path'],base_dir);candidate=artifact_path(item['candidate_path'],base_dir);assert sha(source)==item['input_sha256'] and sha(candidate)==item['candidate_sha256']
 assert source_contract(source)==source_contract(candidate),'source interface contract mismatch'
 gates,inputs,outputs,constants=parse_primitive(source);assert outputs,'no output ports';certificate=json.loads(identities_path.read_text());assert artifact_path(certificate['source_path'],identities_path.parent)==source.resolve(),'identity source path mismatch'
 # Independent original-gate truth evaluator with complete cut boundaries.
 def ev(n,values,memo):
  if n in values:return values[n]
  if n in constants:return constants[n]
  if n in memo:return memo[n]
  if n not in gates:raise ValueError('cut does not cover all primary inputs: '+n)
  op,aa=gates[n];v=[ev(a,values,memo) for a in aa]
  if op=='buf':z=v[0]
  elif op=='not':z=1-v[0]
  elif op in ['and','nand']:z=int(all(v));z=1-z if op=='nand' else z
  elif op in ['or','nor']:z=int(any(v));z=1-z if op=='nor' else z
  else:z=sum(v)%2;z=1-z if op=='xnor' else z
  memo[n]=z;return z
 checked=0;negative_identities=0;rewrites={}
 for ident in certificate['identities']:
  leaves=ident['leaves'];assert len(leaves)==len(set(leaves)) and len(leaves) in (2,3)
  assert ident['exhaustive_assignments_checked']==1<<len(leaves)
  assert all(v in inputs or v in gates for v in leaves)
  sn=ident['sum'];cn=ident['carry'];assert sn in gates and cn in gates
  coeff=ident['leaf_coefficients_rhs'];const=ident['constant_rhs'];cc=ident['carry_coefficient_on_lhs'];assert cc in [-2,2] and all(c in [-1,1] for c in coeff)
  for assignment in itertools.product([0,1],repeat=len(leaves)):
   values=dict(zip(leaves,assignment));lhs=ev(sn,values,{})+cc*ev(cn,values,{});rhs=const+sum(c*v for c,v in zip(coeff,assignment));assert lhs==rhs,'invalid local identity';assert lhs!=rhs+1;checked+=1
  negative_identities+=1
  rw=dict(zip(leaves,coeff));rw[cn]=rw.get(cn,0)-cc
  if const:rw['1']=const
  assert rw==ident['rewrite'];assert sn not in rewrites;rewrites[sn]=rw
 assert rewrites==certificate['rewrites']
 sliced_outputs=set(sliced_outputs or []);assert sliced_outputs<=set(outputs),'unknown sliced output'
 case_splits=list(case_splits or [{}]);case_bits=sorted(case_splits[0]) if case_splits and case_splits[0] else []
 assert all(sorted(assignment)==case_bits and all(value in [0,1] for value in assignment.values()) for assignment in case_splits),'inconsistent case-split assignments'
 assert set(case_bits)<=inputs,'case split must fix only original primary inputs'
 assert len(case_splits)==1<<len(case_bits) and {tuple(assignment[bit] for bit in case_bits) for assignment in case_splits}==set(itertools.product([0,1],repeat=len(case_bits))),'case splits do not cover the complete Boolean cube'
 assert not case_bits or sliced_outputs==set(outputs),'case-split replay requires every output to be sliced'
 # Lower the candidate once.  Each output is then interpreted separately at
 # its declared modular width so unrelated narrow outputs cannot invalidate a
 # wider output's range proof.
 wordjson=out/'candidate_word.json';word_opt='opt' if optimize_word else 'opt_clean';command=[str(yosys),'-p',f'read_verilog {candidate}; hierarchy -check -top top; proc; {word_opt}; check -assert; write_json {wordjson}']
 process=subprocess.run(command,cwd=Path.cwd(),capture_output=True,text=True,timeout=60);(out/'candidate_lower.log').write_text(process.stdout+process.stderr);assert process.returncode==0
 design=json.loads(wordjson.read_text())['modules']['top'];results={}
 for output,bits in outputs.items():
  declared_width=len(bits);width=declared_width;high_zero_bits=[]
  if trim_constant_high_zero:
   while width>1:
    try:value=ev(bits[width-1],{},{})
    except ValueError:break
    if value!=0:break
    high_zero_bits.append({'bit':width-1,'signal':bits[width-1],'proved_constant':0});width-=1
  low_bits=bits[:width];mod=1<<width
  single_design={**design,'ports':{n:p for n,p in design['ports'].items() if p['direction']=='input' or n==output}}
  cell_bounds=[];condition_checks=[];output_bounds={};cp,cinputs=word_poly(single_design,declared_width,cell_bounds,condition_checks,output_bounds);assert cinputs==inputs and set(cp)=={output},'interface mismatch';assert len(design['ports'][output]['bits'])==declared_width
  upper_bound=output_bounds[output]
  if width<declared_width:assert upper_bound<(1<<width),'candidate upper-bound certificate insufficient'
  cp_reduced={t:c%mod for t,c in cp[output].items() if c%mod}
  def plus(a,b,k=1):
   d=a.copy()
   for t,c in b.items():
    value=(d.get(t,0)+k*c)%mod
    if value:d[t]=value
    else:d.pop(t,None)
   return d
  def product(a,b):
   d={}
   for x,c in a.items():
    for y,e in b.items():d=plus(d,{x|y:c*e})
   return d
  ordered=[];visited=set();visiting=set()
  def topo(n):
   if n in visited:return
   assert n not in visiting,'rewrite graph cycle';visiting.add(n)
   if n in gates:
    for v in (rewrites[n] if n in rewrites else gates[n][1]):topo(v)
    ordered.append(n)
   visiting.remove(n);visited.add(n)
  for n in low_bits:topo(n)
  dependencies={n:[v for v in (rewrites[n] if n in rewrites else gates[n][1]) if v in gates] for n in ordered}
  slice_of={}
  def mark(n,b):
   if n not in gates or slice_of.get(n,width)<=b:return
   slice_of[n]=b
   for v in dependencies[n]:mark(v,b)
  for b,n in enumerate(low_bits):mark(n,b)
  assert set(slice_of)==set(ordered),'sliced replay did not classify every gate'
  by_slice={b:[n for n in reversed(ordered) if slice_of[n]==b] for b in range(width)}
  def specialized_constants(assignment):
   """Independent Boolean-DAG normalization for branch-local constants."""
   memo={};active=set()
   def invert(lit):return 1-lit if isinstance(lit,int) else (lit[0],not lit[1])
   def conjunction(values,dual=False):
    if dual:return invert(conjunction([invert(x) for x in values]))
    if 0 in values:return 0
    terms={x for x in values if x!=1}
    if any(invert(x) in terms for x in terms):return 0
    if not terms:return 1
    if len(terms)==1:return next(iter(terms))
    return (('conjunction',tuple(sorted(terms,key=repr))),False)
   def parity(values):
    phase=0;terms=set()
    for lit in values:
     if isinstance(lit,int):phase^=lit;continue
     base,inv=lit;phase^=inv
     if base in terms:terms.remove(base)
     else:terms.add(base)
    if not terms:return phase
    if len(terms)==1:return (next(iter(terms)),bool(phase))
    return (('parity',tuple(sorted(terms,key=repr))),bool(phase))
   def expression(n):
    if n in constants:return constants[n]
    if n in assignment:return assignment[n]
    if n in memo:return memo[n]
    if n not in gates:return (('input',n),False)
    assert n not in active,'specialized reference cycle';active.add(n)
    op,aa=gates[n];values=[expression(v) for v in aa]
    if op=='buf':result=values[0]
    elif op=='not':result=invert(values[0])
    elif op in ['and','nand']:result=conjunction(values);result=invert(result) if op=='nand' else result
    elif op in ['or','nor']:result=conjunction(values,True);result=invert(result) if op=='nor' else result
    else:result=parity(values);result=invert(result) if op=='xnor' else result
    active.remove(n);memo[n]=result;return result
   for n in ordered:expression(n)
   fixed={n:value for n,value in memo.items() if isinstance(value,int)}
   aliases={n:(value[0][1],value[1]) for n,value in memo.items() if not isinstance(value,int) and value[0][0]=='input'}
   return fixed,aliases
  def restrict_candidate(assignment):
   restricted={}
   for term,c in cp_reduced.items():
    if any(bit in term and not assignment[bit] for bit in assignment):continue
    reduced=term-set(assignment);restricted[reduced]=(restricted.get(reduced,0)+c)%mod
    if not restricted[reduced]:del restricted[reduced]
   return restricted
  branch_records=[];last_poly={};overall_peak=0
  for assignment in case_splits:
   fixed,aliases=specialized_constants(assignment) if assignment else ({},{})
   candidate_branch=restrict_candidate(assignment)
   def known_value(n):
    if n in constants:return constants[n]
    if n in assignment:return assignment[n]
    return fixed.get(n)
   # Propagate branch constants through the independently checked arithmetic
   # identities as well as through ordinary primitive controlling values.
   for n in ordered:
    if n in fixed:continue
    if n in rewrites:
     values={v:known_value(v) for v in rewrites[n]}
     if all(value is not None for value in values.values()):
      value=sum(rewrites[n][v]*values[v] for v in values);assert value in [0,1];fixed[n]=value
     continue
    op,aa=gates[n];values=[known_value(v) for v in aa];value=None
    if op=='buf' and values[0] is not None:value=values[0]
    elif op=='not' and values[0] is not None:value=1-values[0]
    elif op in ['and','nand']:
     if 0 in values:value=0
     elif all(v==1 for v in values):value=1
     if value is not None and op=='nand':value=1-value
    elif op in ['or','nor']:
     if 1 in values:value=1
     elif all(v==0 for v in values):value=0
     if value is not None and op=='nor':value=1-value
    elif op in ['xor','xnor'] and all(v is not None for v in values):
     value=sum(values)%2
     if op=='xnor':value=1-value
    if value is not None:fixed[n]=value
   def variable(n):
    if n in constants:return {frozenset():constants[n]} if constants[n] else {}
    if n in assignment:return {frozenset():assignment[n]} if assignment[n] else {}
    if n in fixed:return {frozenset():fixed[n]} if fixed[n] else {}
    if n in aliases:
     base=variable(aliases[n][0])
     return plus({frozenset():1},base,-1) if aliases[n][1] else base
    return {frozenset([n]):1}
   assert not assignment,'cone replay currently supports only all-free-input obligations'
   support_cache={};cone_polynomials={};cone_assignments=0
   def cone_support(n):
    if n in constants:return set()
    if n in inputs:return {n}
    if n in support_cache:return support_cache[n]
    assert n in gates,'undefined cone variable'
    acc=set()
    for v in gates[n][1]:
     vv=cone_support(v)
     if vv is None:acc=None;break
     acc.update(vv)
     if len(acc)>cone_input_cap:acc=None;break
    support_cache[n]=acc;return acc
   for node in ordered:
    leaves=cone_support(node)
    if leaves is None:continue
    leaves=sorted(leaves);values={}
    for assignment_bits in itertools.product([0,1],repeat=len(leaves)):
     selected=frozenset(leaves[i] for i,v in enumerate(assignment_bits) if v)
     values[selected]=ev(node,dict(zip(leaves,assignment_bits)),{})
    # Independent subset-inclusion inversion (not the primary fast Mobius loop).
    coeff={}
    for selected in sorted(values,key=lambda x:(len(x),sorted(x))):
     coeff[selected]=values[selected]-sum(c for subset,c in coeff.items() if subset<selected)
    for selected,value in values.items():assert sum(c for subset,c in coeff.items() if subset<=selected)==value,'invalid cone polynomial'
    cone_polynomials[node]={t:c%mod for t,c in coeff.items() if c%mod};cone_assignments+=len(values)
   def equation(n):
    if n in cone_polynomials:return cone_polynomials[n]
    if n in fixed:return variable(n)
    if n in aliases:return variable(n)
    if n in rewrites:
     z={}
     for v,c in rewrites[n].items():z=plus(z,variable(v),c)
     return z
    op,aa=gates[n];z=variable(aa[0])
    for a in aa[1:]:
     p=variable(a)
     z=product(z,p) if op in ['and','nand'] else plus(plus(z,p),product(z,p),-1 if op in ['or','nor'] else -2)
    return plus({frozenset():1},z,-1) if op in ['not','nand','nor','xnor'] else z
   if output in sliced_outputs:
    target_by_slice={b:[] for b in range(width)}
    for term,c in candidate_branch.items():target_by_slice[(c&-c).bit_length()-1].append((term,c))
    poly={};incidence={};peak=0
    def put(term,c):
     before=poly.get(term,0);after=(before+c)%mod
     if after:
      poly[term]=after
      if not before:
       for v in term:incidence.setdefault(v,set()).add(term)
     elif before:
      del poly[term]
      for v in term:incidence[v].discard(term)
    for b,n in enumerate(low_bits):put(frozenset([n]),1<<b)
    for term,c in candidate_branch.items():put(term,-c)
    pending=set(ordered);users={n:0 for n in ordered}
    for n in pending:
     for v in dependencies[n]:users[v]+=1
    ready={n for n in pending if users[n]==0};substitutions={n:equation(n) for n in pending}
    while pending:
     assert ready,'cone replay graph cycle'
     n=min(ready,key=lambda v:(len(incidence.get(v,set()))*max(1,len(substitutions[v])),len(substitutions[v]),v))
     ready.remove(n);pending.remove(n)
     for v in dependencies[n]:
      users[v]-=1
      if users[v]==0 and v in pending:ready.add(v)
     if True:
      sub=substitutions[n]
      for term in list(incidence.get(n,set())):
       c=poly[term];put(term,-c);base=term-{n}
       for t,k in sub.items():put(base|t,c*k)
      peak=max(peak,len(poly));assert len(poly)<term_cap,'sliced replay term cap'
    assert not poly,'sliced reference-minus-candidate remainder is nonzero'
   else:
    poly={frozenset([n]):1<<b for b,n in enumerate(low_bits)};peak=len(poly)
    for n in reversed(ordered):
     sub=equation(n);z={}
     for term,c in poly.items():
      if n in term:
       for t,k in sub.items():z=plus(z,{(term-{n})|t:c*k})
      else:z=plus(z,{term:c})
     poly=z;peak=max(peak,len(poly));assert len(poly)<term_cap,'replay term cap'
    assert all(set(t)<=inputs-set(assignment) for t in poly),'uneliminated/non-primary variable'
    assert candidate_branch==poly,'candidate polynomial differs'
   last_poly=poly;overall_peak=max(overall_peak,peak)
   branch_records.append({'assignment':assignment,'free_primary_inputs':sorted(inputs-set(assignment)),'fixed_reference_gates':len(fixed),'primary_input_alias_gates':len(aliases),'candidate_terms_after_restriction':len(candidate_branch),'term_count':len(poly),'replay_max_terms':peak,'zero_remainder':not poly if output in sliced_outputs else None})
  if primary_polynomial is not None and not case_bits:
   derived=json.loads(primary_polynomial.read_text());archived={frozenset(t['variables']):t['coefficient'] for t in derived['polynomial']};assert last_poly==archived,'independent replay differs from primary reduction'
  if output in sliced_outputs:negative={frozenset():mod-1};assert negative
  else:negative=plus(cp_reduced,{frozenset():1});assert negative!=last_poly
  strategy='exhaustive-case-split-significance-sliced-reference-minus-candidate' if case_bits else ('all-output-dynamic-small-cone-reference-minus-candidate' if output in sliced_outputs else 'full-reference-polynomial-equality')
  results[output]={'bits':declared_width,'proved_low_bits':width,'reference_high_zero_bits':high_zero_bits,'candidate_structural_unsigned_upper_bound_inclusive':upper_bound,'candidate_narrow_cell_bound_certificates':cell_bounds,'candidate_condition_truth_table_certificates':condition_checks,'modulus':mod,'term_count':len(last_poly),'replay_max_terms':overall_peak,'proof_strategy':strategy,'case_split_bits':case_bits,'case_split_complete_boolean_cube':bool(case_bits),'case_split_branches':branch_records if case_bits else [],'small_primary_cones':len(cone_polynomials),'small_cone_assignments':cone_assignments,'candidate_polynomial_equal':True,'add_one_negative_control_rejected':True,'polynomial':[{'variables':sorted(t),'coefficient':c} for t,c in sorted(last_poly.items(),key=lambda x:(len(x[0]),sorted(x[0])))]}
 verifier_snapshot=out/'verifier_sources';verifier_snapshot.mkdir()
 verifier_sources=[]
 for original in [*sorted(HERE.glob('*.py')),HERE.parent/'tooling.py']:
  retained=verifier_snapshot/original.name;retained.write_bytes(original.read_bytes());verifier_sources.append(retained)
 record={**item,'status':'strict_algebraic_equivalence','outputs':results,'local_identities':len(rewrites),'local_exhaustive_assignments':checked,'local_negative_controls_rejected':negative_identities,'candidate_lowering_command':command,'source_hashes':{str(p.resolve()):sha(p) for p in [source,candidate,identities_path,*verifier_sources,yosys]},'all_original_outputs_compared':set(results)==set(outputs),'all_final_variables_are_primary_inputs':True,'case_split_bits':case_bits,'case_split_branch_count':len(case_splits) if case_bits else 0,'case_split_complete_boolean_cube':bool(case_bits),'algebra':'integers modulo 2**W, Boolean variables satisfy x**2=x; exhaustive case splits cover both values of every listed split bit','runtime_seconds':time.monotonic()-start,'source_interface_contract':source_contract(source),'scope':'exact algebraic proof of the hash-bound source/candidate pair; no simulation or unproved input assumptions'}
 assert sha(source)==item['input_sha256'] and sha(candidate)==item['candidate_sha256'],'source changed during proof'
 (out/'record.json').write_text(json.dumps(record,indent=2)+'\n');print(record['status'],record['runtime_seconds']);return record

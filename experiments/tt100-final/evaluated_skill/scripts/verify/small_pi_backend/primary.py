#!/usr/bin/env python3
"""Exact sparse Boolean polynomial elimination of a primitive output word.
All operations are integer polynomials modulo 2**output_width and x*x=x.
A completed polynomial is an identity of the parsed original gate network.
A resource cap is UNKNOWN, never a certificate. No cutpoints or assumptions.
"""
import argparse,collections,hashlib,json,re,time
from pathlib import Path

def specialize_boolean_dag(gates,order,assignments):
 """Hash-cons exact Boolean identities after fixing an exhaustive-case branch."""
 signal_lit={};representative={};fixed={};aliases={};active=set();visible=set(order)
 def neg(lit):return 1-lit if isinstance(lit,int) else (lit[0],not lit[1])
 def bind(name,lit):
  signal_lit[name]=lit
  if isinstance(lit,int):fixed[name]=lit
  elif name not in visible:return
  elif lit in representative and representative[lit] not in gates:aliases[name]=(representative[lit],False)
  elif neg(lit) in representative and representative[neg(lit)] not in gates:aliases[name]=(representative[neg(lit)],True)
  else:representative[lit]=name
 def literal(name):
  if name in ("1'b0","1'h0","1'd0",'0'):return 0
  if name in ("1'b1","1'h1","1'd1",'1'):return 1
  if name in assignments:return assignments[name]
  if name in signal_lit:return signal_lit[name]
  if name in gates:
   assert name not in active,'candidate specialization cycle';active.add(name)
   op,args=gates[name];lit=operation(op,[literal(v) for v in args]);active.remove(name);bind(name,lit);return lit
  lit=(('var',name),False);signal_lit[name]=lit;representative.setdefault(lit,name);return lit
 def conjunction(values,dual=False):
  # OR is derived through De Morgan so one checked implementation handles both.
  if dual:return neg(conjunction([neg(x) for x in values]))
  if 0 in values:return 0
  terms={x for x in values if x!=1}
  if any(neg(x) in terms for x in terms):return 0
  if not terms:return 1
  if len(terms)==1:return next(iter(terms))
  return (('and',tuple(sorted(terms,key=repr))),False)
 def exclusive_or(values):
  parity=0;terms=set()
  for lit in values:
   if isinstance(lit,int):parity^=lit;continue
   base,inverted=lit;parity^=inverted
   if base in terms:terms.remove(base)
   else:terms.add(base)
  if not terms:return parity
  if len(terms)==1:return (next(iter(terms)),bool(parity))
  return (('xor',tuple(sorted(terms,key=repr))),bool(parity))
 def operation(op,values):
  if op=='buf':assert len(values)==1;return values[0]
  if op=='not':assert len(values)==1;return neg(values[0])
  if op in ['and','nand']:result=conjunction(values)
  elif op in ['or','nor']:result=conjunction(values,True)
  else:result=exclusive_or(values)
  return neg(result) if op in ['nand','nor','xnor'] else result
 for name in order:literal(name)
 return fixed,aliases

def reduce(path,output,width,cap,seconds,rewrites=None,elimination_order='dynamic',assignments=None):
 start=time.monotonic();text=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(),flags=re.S);gates={};ops=collections.Counter()
 for stmt in text.split(';'):
  stmt=stmt.strip()
  if not stmt or stmt=='endmodule' or re.match(r'^(module|input|output|wire)\b',stmt):continue
  m=re.fullmatch(r'(and|nand|or|nor|xor|xnor|not|buf)\s+\w+\s*\(([^()]*)\)',stmt)
  if not m:raise ValueError('Unsupported syntax:'+stmt[:160])
  op=m[1];args=[re.sub(r'\s+','',x) for x in m[2].split(',')];assert args[0] not in gates;gates[args[0]]=(op,args[1:]);ops[op]+=1
 primitive_gates=dict(gates);rewrites=rewrites or {}
 for v,rw in rewrites.items():
  assert v in gates
  gates[v]=('certified:'+v,list(rw))
 order=[];seen=set();visiting=set()
 def visit(n):
  if n in seen:return
  if n in visiting:raise ValueError('cycle')
  visiting.add(n)
  if n in gates:
   for a in gates[n][1]:visit(a)
   order.append(n)
  visiting.remove(n);seen.add(n)
 for b in range(width):visit(f'{output}[{b}]')
 order_rank={v:i for i,v in enumerate(order)}
 mod=1<<width;assignments=assignments or {};assert all(v in [0,1] for v in assignments.values())
 # DAG specialization is useful only for a nonempty exhaustive-case branch.
 # Building symbolic structural expressions for an unsplit large multiplier
 # adds substantial time and memory while discovering no fixed values.
 fixed,aliases=specialize_boolean_dag(primitive_gates,order,assignments) if assignments else ({},{})
 def known(v):
  if v in ("1'b0","1'h0","1'd0",'0'):return 0
  if v in ("1'b1","1'h1","1'd1",'1'):return 1
  if v in assignments:return assignments[v]
  return fixed.get(v)
 for v in order:
  if v in fixed or v in aliases:continue
  op,aa=gates[v]
  if op.startswith('certified:'):
   values={n:known(n) for n in rewrites[v]}
   if all(x is not None for x in values.values()):
    value=sum(rewrites[v][n]*values[n] for n in values)
    assert value in [0,1];fixed[v]=value
   continue
  values=[known(a) for a in aa];value=None
  if op=='buf' and values[0] is not None:value=values[0]
  elif op=='not' and values[0] is not None:value=1-values[0]
  elif op in ['and','nand']:
   if 0 in values:value=0
   elif all(x==1 for x in values):value=1
   if value is not None and op=='nand':value=1-value
  elif op in ['or','nor']:
   if 1 in values:value=1
   elif all(x==0 for x in values):value=0
   if value is not None and op=='nor':value=1-value
  elif op in ['xor','xnor'] and all(x is not None for x in values):
   value=sum(values)%2
   if op=='xnor':value=1-value
  if value is not None:fixed[v]=value
 def pvar(v):
  if v in ("1'b0","1'h0","1'd0",'0'):return {}
  if v in ("1'b1","1'h1","1'd1",'1'):return {frozenset():1}
  if v in assignments:return {frozenset():assignments[v]} if assignments[v] else {}
  if v in fixed:return {frozenset():fixed[v]} if fixed[v] else {}
  if v in aliases:
   base=pvar(aliases[v][0])
   return add({frozenset():1},base,-1) if aliases[v][1] else base
  return {frozenset([v]):1}
 def add(a,b,k=1):
  d=a.copy()
  for t,c in b.items():
   z=(d.get(t,0)+k*c)%mod
   if z:d[t]=z
   elif t in d:del d[t]
  return d
 def mul(a,b):
  d={}
  for x,c in a.items():
   for y,e in b.items():
    t=x|y;z=(d.get(t,0)+c*e)%mod
    if z:d[t]=z
    elif t in d:del d[t]
  return d
 def gatepoly(op,aa):
  if op.startswith('certified:'):
   result={}
   for v,c in rewrites[op[len('certified:'):]].items():result=add(result,pvar(v),c)
   return result
  args=[pvar(a) for a in aa];one={frozenset():1}
  if op in ['not','buf']:assert len(args)==1;return add(one,args[0],-1) if op=='not' else args[0]
  result=args[0]
  for a in args[1:]:
   if op in ['and','nand']:result=mul(result,a)
   elif op in ['or','nor']:result=add(add(result,a),mul(result,a),-1)
   else:result=add(add(result,a),mul(result,a),-2)
  return add(one,result,-1) if op in ['nand','nor','xnor'] else result
 poly={frozenset([f'{output}[{b}]']):1<<b for b in range(width)}
 incidence=collections.defaultdict(set)
 for t in poly:
  for v in t:incidence[v].add(t)
 maxterms=len(poly);trace=[]
 def put(t,c):
  before=poly.get(t,0);after=(before+c)%mod
  if after:
   poly[t]=after
   if not before:
    for v in t:incidence[v].add(t)
  elif before:
   del poly[t]
   for v in t:incidence[v].discard(t)
 if elimination_order not in ['dynamic','fixed']:
  raise ValueError('unsupported elimination order: '+elimination_order)
 dependencies={v:[x for x in gates[v][1] if x in gates] for v in order}
 remaining_users=collections.Counter()
 for v in order:
  for x in dependencies[v]:remaining_users[x]+=1
 fixed_order=list(reversed(order));ready={v for v in order if remaining_users[v]==0}
 substitutions={v:(pvar(v) if v in fixed or v in aliases else gatepoly(*gates[v])) for v in order}
 eliminated=set()
 for i in range(len(order)):
  if elimination_order=='fixed':v=fixed_order[i]
  else:
   if not ready:raise ValueError('no reverse-topological gate is ready')
   # Every ready gate has no uneliminated consumer, so choosing among ready
   # gates cannot reintroduce an already eliminated variable.  Prefer the
   # substitution with the smallest current upper bound on generated terms.
   v=min(ready,key=lambda x:(len(incidence[x])*max(1,len(substitutions[x])),len(substitutions[x]),-order_rank[x]))
   ready.remove(v)
  terms=list(incidence[v]);sub=substitutions[v]
  for t in terms:
   c=poly[t];put(t,-c);base=t-{v}
   for x,k in sub.items():put(base|x,c*k)
  eliminated.add(v)
  for x in dependencies[v]:
   remaining_users[x]-=1
   if remaining_users[x]==0 and x not in eliminated:ready.add(x)
  maxterms=max(maxterms,len(poly))
  if i%100==0:trace.append({'eliminated_gates':i,'terms':len(poly),'ready_gates':len(ready),'seconds':time.monotonic()-start})
  if len(poly)>cap or time.monotonic()-start>seconds:return {'status':'unknown_resource_limit','terms':len(poly),'max_terms':maxterms,'eliminated_gates':i,'gate_count':len(order),'runtime_seconds':time.monotonic()-start,'trace':trace}
 if any(v in gates for t in poly for v in t):raise ValueError('gate variable remains after elimination')
 return {'status':'exact_polynomial_derived','source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'output':output,'width':width,'fixed_primary_inputs':assignments,'gate_count':len(order),'all_gate_count':len(gates),'gate_types':dict(ops),'elimination_order':elimination_order,'terms':len(poly),'max_terms':maxterms,'runtime_seconds':time.monotonic()-start,'trace':trace,'polynomial':[{'variables':sorted(t),'coefficient':c} for t,c in sorted(poly.items(),key=lambda x:(len(x[0]),sorted(x[0])))]}

def reduce_difference_sliced(path,output,width,target,cap,seconds,rewrites=None,assignments=None,cone_input_cap=6):
 """Reduce reference_word-target by output-significance slices.

 ``target`` is a sparse polynomial over unconstrained primary-input bits.  It
 is part of the goal, never an assumption.  A zero remainder is therefore a
 full modular identity.  Gates are eliminated only after every output bit
 that can consume them has entered the remainder.
 """
 if assignments:raise ValueError('small-PI backend does not accept case assignments')
 if not 1<=cone_input_cap<=8:raise ValueError('cone input cap must be 1..8')
 start=time.monotonic();text=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(),flags=re.S);gates={};ops=collections.Counter()
 for stmt in text.split(';'):
  stmt=stmt.strip()
  if not stmt or stmt=='endmodule' or re.match(r'^(module|input|output|wire)\b',stmt):continue
  m=re.fullmatch(r'(and|nand|or|nor|xor|xnor|not|buf)\s+\w+\s*\(([^()]*)\)',stmt)
  if not m:raise ValueError('Unsupported syntax:'+stmt[:160])
  op=m[1];args=[re.sub(r'\s+','',x) for x in m[2].split(',')];assert args[0] not in gates;gates[args[0]]=(op,args[1:]);ops[op]+=1
 primitive_gates=dict(gates);rewrites=rewrites or {}
 for v,rw in rewrites.items():
  assert v in gates;gates[v]=('certified:'+v,list(rw))
 order=[];seen=set();visiting=set()
 def visit(n):
  if n in seen:return
  if n in visiting:raise ValueError('cycle')
  visiting.add(n)
  if n in gates:
   for a in gates[n][1]:visit(a)
   order.append(n)
  visiting.remove(n);seen.add(n)
 for b in range(width):visit(f'{output}[{b}]')
 mod=1<<width;assignments=assignments or {};assert all(v in [0,1] for v in assignments.values())
 fixed,aliases=specialize_boolean_dag(primitive_gates,order,assignments) if assignments else ({},{})
 def known(v):
  if v in ("1'b0","1'h0","1'd0",'0'):return 0
  if v in ("1'b1","1'h1","1'd1",'1'):return 1
  if v in assignments:return assignments[v]
  return fixed.get(v)
 for v in order:
  if v in fixed or v in aliases:continue
  op,aa=gates[v]
  if op.startswith('certified:'):
   values={n:known(n) for n in rewrites[v]}
   if all(x is not None for x in values.values()):
    value=sum(rewrites[v][n]*values[n] for n in values)
    assert value in [0,1];fixed[v]=value
   continue
  values=[known(a) for a in aa];value=None
  if op=='buf' and values[0] is not None:value=values[0]
  elif op=='not' and values[0] is not None:value=1-values[0]
  elif op in ['and','nand']:
   if 0 in values:value=0
   elif all(x==1 for x in values):value=1
   if value is not None and op=='nand':value=1-value
  elif op in ['or','nor']:
   if 1 in values:value=1
   elif all(x==0 for x in values):value=0
   if value is not None and op=='nor':value=1-value
  elif op in ['xor','xnor'] and all(x is not None for x in values):
   value=sum(values)%2
   if op=='xnor':value=1-value
  if value is not None:fixed[v]=value
 def pvar(v):
  if v in ("1'b0","1'h0","1'd0",'0'):return {}
  if v in ("1'b1","1'h1","1'd1",'1'):return {frozenset():1}
  if v in assignments:return {frozenset():assignments[v]} if assignments[v] else {}
  if v in fixed:return {frozenset():fixed[v]} if fixed[v] else {}
  if v in aliases:
   base=pvar(aliases[v][0])
   return add({frozenset():1},base,-1) if aliases[v][1] else base
  return {frozenset([v]):1}
 def add(a,b,k=1):
  d=a.copy()
  for t,c in b.items():
   z=(d.get(t,0)+k*c)%mod
   if z:d[t]=z
   else:d.pop(t,None)
  return d
 def mul(a,b):
  d={}
  for x,c in a.items():
   for y,e in b.items():
    t=x|y;z=(d.get(t,0)+c*e)%mod
    if z:d[t]=z
    else:d.pop(t,None)
  return d
 support_memo={};direct={};native_constants={"1'b0":0,"1'h0":0,"1'd0":0,'0':0,"1'b1":1,"1'h1":1,"1'd1":1,'1':1}
 def support(n):
  if n in native_constants:return set()
  if n in support_memo:return support_memo[n]
  if n not in primitive_gates:return {n}
  acc=set()
  for a in primitive_gates[n][1]:
   aa=support(a)
   if aa is None:acc=None;break
   acc.update(aa)
   if len(acc)>cone_input_cap:acc=None;break
  support_memo[n]=acc;return acc
 def truth(n,leaves):
  size=1<<len(leaves);mask=(1<<size)-1;memo={}
  def ev(v):
   if v in native_constants:return mask if native_constants[v] else 0
   if v in memo:return memo[v]
   if v in leaves:z=sum(((i>>leaves.index(v))&1)<<i for i in range(size))
   else:
    op,aa=primitive_gates[v];vals=[ev(a) for a in aa];z=vals[0]
    if op=='not':z^=mask
    elif op!='buf':
     for x in vals[1:]:z=z&x if op in ['and','nand'] else z|x if op in ['or','nor'] else z^x
     if op in ['nand','nor','xnor']:z^=mask
   memo[v]=z;return z
  values=[(ev(n)>>i)&1 for i in range(size)]
  coeff=values[:]
  for i in range(len(leaves)):
   for j in range(size):
    if j&(1<<i):coeff[j]-=coeff[j^(1<<i)]
  for j in range(size):assert sum(coeff[k] for k in range(size) if k&j==k)==values[j]
  return {frozenset(leaves[i] for i in range(len(leaves)) if k&(1<<i)):c%mod for k,c in enumerate(coeff) if c%mod}
 for n in order:
  ss=support(n)
  if ss is not None:direct[n]=truth(n,sorted(ss))
 def equation(v):
  if v in direct:return direct[v]
  if v in fixed:return {frozenset():fixed[v]} if fixed[v] else {}
  if v in aliases:return pvar(v)
  op,aa=gates[v]
  if op.startswith('certified:'):
   result={}
   for n,c in rewrites[v].items():result=add(result,pvar(n),c)
   return result
  args=[pvar(a) for a in aa];one={frozenset():1}
  if op in ['not','buf']:return add(one,args[0],-1) if op=='not' else args[0]
  result=args[0]
  for a in args[1:]:
   if op in ['and','nand']:result=mul(result,a)
   elif op in ['or','nor']:result=add(add(result,a),mul(result,a),-1)
   else:result=add(add(result,a),mul(result,a),-2)
  return add(one,result,-1) if op in ['nand','nor','xnor'] else result
 dependencies={v:[x for x in gates[v][1] if x in gates] for v in order}
 slice_of={}
 def mark(n,b):
  if n not in gates or slice_of.get(n,width)<=b:return
  slice_of[n]=b
  for x in dependencies[n]:mark(x,b)
 for b in range(width):mark(f'{output}[{b}]',b)
 assert set(slice_of)==set(order)
 gates_by_slice=collections.defaultdict(list)
 for v in reversed(order):gates_by_slice[slice_of[v]].append(v)
 buckets=collections.defaultdict(list)
 for term,coefficient in target.items():
  c=coefficient%mod
  if not c:continue
  if any(v in gates for v in term):raise ValueError('target contains a reference-gate variable')
  valuation=(c&-c).bit_length()-1;buckets[valuation].append((term,c))
 poly={};incidence=collections.defaultdict(set);maxterms=0;trace=[];eliminated=0
 def put(term,coefficient):
  before=poly.get(term,0);after=(before+coefficient)%mod
  if after:
   poly[term]=after
   if not before:
    for n in term:incidence[n].add(term)
  elif before:
   del poly[term]
   for n in term:incidence[n].discard(term)
 for bit in range(width):put(frozenset([f'{output}[{bit}]']),1<<bit)
 for term,c in target.items():put(term,-c)
 gates_by_slice={0:list(reversed(order))}
 for b in [0]:
  pending=set(gates_by_slice[b]);users=collections.Counter(x for v in pending for x in dependencies[v] if x in pending)
  ready={v for v in pending if not users[v]};subs={v:equation(v) for v in pending}
  while pending:
   assert ready,'dynamic sliced dependency cycle'
   v=min(ready,key=lambda n:(len(incidence[n])*max(1,len(subs[n])),len(subs[n]),n));ready.remove(v);pending.remove(v)
   for x in dependencies[v]:
    if x in pending:
     users[x]-=1
     if users[x]==0:ready.add(x)
   sub=subs[v];terms=list(incidence[v])
   for term in terms:
    c=poly[term];put(term,-c);base=term-{v}
    for replacement,k in sub.items():put(base|replacement,c*k)
   eliminated+=1;maxterms=max(maxterms,len(poly))
   if len(poly)>cap or time.monotonic()-start>seconds:
    return {'status':'unknown_resource_limit','output':output,'width':width,'terms':len(poly),'max_terms':maxterms,'eliminated_gates':eliminated,'gate_count':len(order),'runtime_seconds':time.monotonic()-start,'trace':trace}
  trace.append({'completed_slice':b,'slice_gates':len(gates_by_slice[b]),'eliminated_gates':eliminated,'terms':len(poly),'seconds':time.monotonic()-start})
 if any(v in gates for term in poly for v in term):raise ValueError('gate variable remains after sliced elimination')
 return {'status':'exact_difference_reduced','equivalent':not poly,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'output':output,'width':width,'fixed_primary_inputs':assignments,'gate_count':len(order),'all_gate_count':len(gates),'gate_types':dict(ops),'terms':len(poly),'max_terms':maxterms,'runtime_seconds':time.monotonic()-start,'trace':trace,'polynomial':[{'variables':sorted(t),'coefficient':c} for t,c in sorted(poly.items(),key=lambda x:(len(x[0]),sorted(x[0])))]}

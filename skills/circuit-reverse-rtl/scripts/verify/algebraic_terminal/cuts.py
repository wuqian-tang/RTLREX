#!/usr/bin/env python3
"""Enumerate exact <=3-leaf Boolean cuts and derive checked adder identities.
Each emitted identity is checked for every value of its two or three cut leaves.
The leaves need not be primary inputs: no relation among them is assumed.
"""
import argparse,collections,itertools,json,re,time
from pathlib import Path

def extract(path,limit=48):
 start=time.monotonic();text=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(),flags=re.S);gates={}
 for stmt in text.split(';'):
  stmt=stmt.strip()
  if not stmt or stmt=='endmodule' or re.match(r'^(module|input|output|wire)\b',stmt):continue
  m=re.fullmatch(r'(and|nand|or|nor|xor|xnor|not|buf)\s+\w+\s*\(([^()]*)\)',stmt)
  if not m:raise ValueError('Unsupported syntax:'+stmt[:160])
  aa=[re.sub(r'\s+','',x) for x in m[2].split(',')];assert aa[0] not in gates;gates[aa[0]]=(m[1],aa[1:])
 order=[];seen=set()
 def dfs(n):
  if n in seen:return
  seen.add(n)
  if n in gates:
   for a in gates[n][1]:dfs(a)
   order.append(n)
 for n in gates:dfs(n)
 rank={v:i for i,v in enumerate(order)}
 cuts={};index=collections.defaultdict(list)
 def base(n):
  if n in cuts:return cuts[n]
  if n in ("1'b0","1'h0","1'd0",'0'):return {():0}
  if n in ("1'b1","1'h1","1'd1",'1'):return {():1}
  return {(n,):2}
 def align(c,t,union):
  positions=[union.index(v) for v in c];tt=0
  for x in range(1<<len(union)):
   sub=sum(((x>>p)&1)<<i for i,p in enumerate(positions));tt|=((t>>sub)&1)<<x
  return tt
 def prune(d):
  if len(d)<=limit:return d
  return dict(sorted(d.items(),key=lambda x:(len(x[0]),-sum(rank.get(v,-1) for v in x[0])))[:limit])
 for i,n in enumerate(order):
  op,aa=gates[n];pool=base(aa[0]).copy()
  for a in aa[1:]:
   nxt={}
   for ca,ta in pool.items():
    for cb,tb in base(a).items():
     u=tuple(sorted(set(ca)|set(cb)))
     if len(u)>3 or u in nxt:continue
     va=align(ca,ta,u);vb=align(cb,tb,u)
     nxt[u]=(va&vb) if op in ['and','nand'] else (va|vb) if op in ['or','nor'] else (va^vb)
   pool=prune(nxt)
  if op in ['not','nand','nor','xnor']:pool={c:t^((1<<(1<<len(c)))-1) for c,t in pool.items()}
  pool[(n,)]=2;cuts[n]=pool
  for c,t in pool.items():
   if len(c) in (2,3):index[c].append((n,t))
  if i%1000==0:print('cuts',i,len(index),time.monotonic()-start,flush=True)
 identities=[];rewrites={}
 for leaves,functions in sorted(index.items(),key=lambda item:-len(item[0])):
  size=len(leaves);parity=(0x96,0x69) if size==3 else (0x6,0x9)
  sums=[x for x in functions if x[1] in parity]
  if not sums:continue
  for sn,st in sums:
   if sn in rewrites:continue
   for cn,ct in functions:
    if cn==sn or ct in parity:continue
    # General signed carry coefficient handles inverted carry encodings.
    for carrycoef in [2,-2]:
     vals=[((st>>x)&1)+carrycoef*((ct>>x)&1) for x in range(1<<size)]
     const=vals[0];coeff=[vals[1<<j]-const for j in range(size)]
     if any(c not in [-1,1] for c in coeff):continue
     if not all(vals[x]==const+sum(coeff[j]*((x>>j)&1) for j in range(size)) for x in range(1<<size)):continue
     # A directed rewrite must not reintroduce a descendant of the sum.
     todo=[cn];visited=set();cyclic=False
     while todo:
      x=todo.pop()
      if x==sn:cyclic=True;break
      if x in visited:continue
      visited.add(x)
      if x in rewrites:todo.extend(k for k in rewrites[x] if k!='1')
      elif x in gates:todo.extend(gates[x][1])
     if cyclic:continue
     rw={n:c for n,c in zip(leaves,coeff)};rw[cn]=rw.get(cn,0)-carrycoef
     if const:rw['1']=const
     identity={'sum':sn,'carry':cn,'leaves':leaves,'sum_truth_table':st,'carry_truth_table':ct,'carry_coefficient_on_lhs':carrycoef,'constant_rhs':const,'leaf_coefficients_rhs':coeff,'exhaustive_assignments_checked':1<<size,'rewrite':rw}
     rewrites[sn]=rw;identities.append(identity);break
    if sn in rewrites:break
 return {'source_path':str(path),'gate_count':len(gates),'cut_limit_per_node':limit,'identity_count':len(identities),'runtime_seconds':time.monotonic()-start,'identities':identities,'rewrites':rewrites,'scope':'Exact local identities over free Boolean leaves; no presumed cross-circuit cutpoint correspondence'}

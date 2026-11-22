"""Lossless residual grouping and exact original-gate coefficient RTL.
Every coefficient is checked modulo its reduced width against zero. Internal
variables are original circuit functions, never free cutpoint assumptions.
"""
import hashlib,json,re
from pathlib import Path
from .certificate import parse_primitive,source_contract

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

def construct(reference,residual_path,domain,out):
 gates,inputs,outputs,constants=parse_primitive(reference)
 record=json.loads(Path(residual_path).read_text())
 if record.get('status')!='exact_terminal_residual_replayed':raise ValueError('unreplayed residual')
 if len(outputs)!=1 or record['declared_output_bits']!=len(next(iter(outputs.values()))):raise ValueError('incomplete output residual')
 if sha(reference)!=record['input_sha256']:raise ValueError('residual source hash mismatch')
 width=record['declared_output_bits'];mod=1<<width;domain=set(domain)
 if not domain or not domain<=inputs:raise ValueError('invalid coefficient input domain')
 outside=inputs-domain;support_memo={};active=set()
 def support(node):
  if node in constants:return set()
  if node in inputs:return {node}
  if node not in gates or node in active:raise ValueError('undefined or cyclic original gate')
  if node not in support_memo:
   active.add(node);support_memo[node]=set().union(*(support(v) for v in gates[node][1]));active.remove(node)
  return support_memo[node]
 groups={};seen=set()
 for item in record['polynomial']:
  variables=item['variables'];coefficient=item['coefficient']
  if len(variables)!=len(set(variables)) or not 0<coefficient<mod:raise ValueError('noncanonical polynomial')
  term=frozenset(variables)
  if term in seen:raise ValueError('duplicate residual term')
  seen.add(term);outer=tuple(sorted(term&outside));inner=tuple(sorted(term-outside))
  if not all(support(v)<=domain for v in inner):raise ValueError('coefficient depends on outside primary inputs')
  groups.setdefault(outer,{})[inner]=coefficient
 # Keep the independent residual's degree-then-original-variable order within
 # each coefficient. Pure lexicographic sorting interleaves low/high-degree
 # terms and changes the long modular add/sub chain seen by synthesis. This
 # canonical ordering affects proof tractability, never the polynomial value.
 ordered=[{'outside_primary_monomial':list(outer),'polynomial':[{'variables':list(inner),'coefficient':c} for inner,c in sorted(poly.items(),key=lambda item:(len(item[0]),item[0]))]} for outer,poly in sorted(groups.items())]
 flattened={frozenset(group['outside_primary_monomial'])|frozenset(term['variables']):term['coefficient'] for group in ordered for term in group['polynomial']}
 original={frozenset(t['variables']):t['coefficient'] for t in record['polynomial']}
 if flattened!=original or sum(len(g['polynomial']) for g in ordered)!=len(original):raise ValueError('grouping not lossless')
 gp=out/'coefficient_groups.json';save(gp,ordered)
 if not ordered:
  audit={'status':'zero_residual','residual_terms':0,'coefficient_count':0,'source_sha256':sha(reference),'residual_sha256':sha(residual_path),'groups_sha256':sha(gp),'all_residual_terms_covered_once':True};save(out/'coefficient_construction.json',audit);return audit
 needed=set();visiting=set()
 def visit(node):
  if node in inputs or node in constants:return
  if node in needed:return
  if node not in gates or node in visiting:raise ValueError('undefined/cyclic native closure')
  visiting.add(node)
  for v in gates[node][1]:visit(v)
  visiting.remove(node);needed.add(node)
 for group in ordered:
  for term in group['polynomial']:
   for node in term['variables']:visit(node)
 # Preserve original scalar gate identifiers: synthesis ordering by net name
 # can expose (or obscure) cancellation in a long coefficient expression.
 # Reserve a synthetic namespace against ALL source signals, not only ports.
 # Bit-selected native nodes need fresh scalar identifiers in this obligation.
 contract=source_contract(reference);input_ports=[(n,w) for n,d,w,_,_ in contract if d=='input'];existing={n for n,_,_,_,_ in contract}|{n.split('[')[0] for n in gates};prefix='terminal_certificate_'
 while any(n.startswith(prefix) for n in existing):prefix+='x'
 digits=max(1,len(str(len(needed)-1)))
 mapping={node:node if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*',node) else f'{prefix}g{i:0{digits}d}' for i,node in enumerate(sorted(needed))}
 def signal(node):return mapping.get(node,node)
 widths=[width-min((t['coefficient']&-t['coefficient']).bit_length()-1 for t in group['polynomial']) for group in ordered]
 names=[f'{prefix}c{i}' for i in range(len(ordered))]
 header=['module top('+', '.join([n for n,w in input_ports]+names)+');']+[f'input [{w-1}:0] {n};' if w>1 else f'input {n};' for n,w in input_ports]+[f'output [{w-1}:0] {name};' for name,w in zip(names,widths)]
 # The source parser distinguishes a scalar from [0:0] by signal spelling.
 # Preserve [0:0] for a width-one original bus rather than silently scalarizing.
 for i,(name,w) in enumerate(input_ports):
  if w==1 and name not in inputs:header[1+i]=f'input [0:0] {name};'
 lines=header+(['wire '+', '.join(mapping.values())+';'] if mapping else [])
 for i,node in enumerate(sorted(needed)):
  op,args=gates[node];lines.append(f'{op} {prefix}instance{i} ('+', '.join([mapping[node]]+[signal(v) for v in args])+');')
 for group,name,w in zip(ordered,names,widths):
  shift=width-w;smallmod=1<<w;pieces=[]
  for item in group['polynomial']:
   co=item['coefficient']>>shift;sign='+'
   if co>=smallmod//2:co=smallmod-co;sign='-'
   bit=' & '.join(signal(v) for v in item['variables']) or "1'b1"
   pieces.append(f" {sign} (({bit}) ? {w}'d{co} : {w}'d0)")
  lines.append(f"assign {name} = {w}'d0"+''.join(pieces)+';')
 ref=out/'coefficient_reference.v';zero=out/'coefficient_zero.v';ref.write_text('\n'.join(lines+['endmodule'])+'\n');zero.write_text('\n'.join(header+[f"assign {name} = {w}'d0;" for name,w in zip(names,widths)]+['endmodule'])+'\n')
 audit={'status':'exact_coefficient_obligations_constructed','source_sha256':sha(reference),'residual_sha256':sha(residual_path),'groups_sha256':sha(gp),'reference_rtl_sha256':sha(ref),'zero_rtl_sha256':sha(zero),'residual_terms':len(original),'coefficient_count':len(ordered),'coefficient_widths':widths,'coefficient_output_bits':sum(widths),'all_original_input_bits':len(inputs),'coefficient_domain_primary_bits':sorted(domain),'original_native_gates_copied':len(needed),'all_residual_terms_covered_once':True,'native_gate_renaming':mapping,'modulus_bits':width};save(out/'coefficient_construction.json',audit);return audit

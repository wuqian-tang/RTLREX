#!/usr/bin/env python3
"""Certify a truncated original output through a complete wider-word embedding.

Plan: reference/candidate/embedded_reference/word_candidate are {path,sha256};
low_bits specifies how many lower bits precede the original output; engine is
algebraic, algebraic-cones, or algebraic-terminal. The last requires a list of
coefficient_inputs. One complete original output word is currently supported.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time

if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify.algebraic.certificate import parse_primitive, source_contract
from verify.composition import require, sha, save, run_command, sat


def verify(plan_path,out,timeout,cap):
    version=sha(__file__);plan=json.loads(plan_path.read_text());files={}
    for key in ('reference','candidate','embedded_reference','word_candidate'):
        r=plan[key];p=Path(r['path']).resolve();require(p.is_file() and sha(p)==r['sha256'],'source hash mismatch: '+key);files[key]=p
    source=source_contract(files['reference']);target=source_contract(files['candidate'])
    embedded=source_contract(files['embedded_reference']);word=source_contract(files['word_candidate'])
    require(source==target and embedded==word,'full paired interfaces differ')
    inputs=[p for p in source if p[1]=='input']
    require(inputs==[p for p in embedded if p[1]=='input'],'embedding changed original inputs')
    original_outputs=[p for p in source if p[1]=='output'];wide_outputs=[p for p in embedded if p[1]=='output']
    require(len(original_outputs)==len(wide_outputs)==1,'one complete output word required')
    name,_,width,_,_=original_outputs[0];wide_name,_,wide_width,_,_=wide_outputs[0]
    low=plan['low_bits'];require(type(low) is int and low>0 and low+width==wide_width,'invalid complete embedding width')
    gates,pi,outputs,_=parse_primitive(files['reference'])
    egates,epi,eoutputs,_=parse_primitive(files['embedded_reference'])
    require(pi==epi and all(egates.get(n)==g for n,g in gates.items()),'original primitive definition changed')
    correspondence=[]
    for i,original in enumerate(outputs[name]):
        node=eoutputs[wide_name][i+low];seen=set()
        while node!=original:
            require(node not in seen and node in egates,'missing/cyclic high-output connection');seen.add(node)
            op,args=egates[node];require(op=='buf' and len(args)==1,'embedding high bit is not the original bit');node=args[0]
        correspondence.append({'original':original,'embedded':eoutputs[wide_name][i+low]})
    save(out/'embedding_audit.json',{'status':'pass','original_gates_unchanged':len(gates),
        'all_original_inputs_free':len(pi),'all_original_output_bits':correspondence,'low_bits':low})
    checker=Path(__file__).with_name('cec.py');engine=plan['engine']
    require(engine in ('algebraic','algebraic-cones','algebraic-terminal'),'unsupported embedding engine')
    folder=out/'wide_word_proof';command=[sys.executable,str(checker),str(files['embedded_reference']),str(files['word_candidate']),
        '--engine',engine,'--strict-cec','--algebraic-timeout',str(timeout),'--algebraic-term-cap',str(cap),
        '--keep-tmp','--tmpdir',str(folder),'--json']
    for port in plan.get('coefficient_inputs',[]):command.extend(['--algebraic-coefficient-input',port])
    for field,flag in [('coefficient_engine','--algebraic-coefficient-engine'),('bdd_node_cap','--algebraic-bdd-node-cap'),('bdd_order','--algebraic-bdd-order')]:
        if field in plan:
            require(engine=='algebraic-terminal','coefficient options require terminal engine')
            command.extend([flag,str(plan[field])])
    if engine=='algebraic':command.extend(['--algebraic-sliced-output',wide_name])
    result=json.loads(run_command(command,folder,timeout+10))
    require(result.get('status')=='pass' and result.get('equivalent') is True,'complete wide word was not proved')
    save(folder/'result.json',result)
    # Build the high-word projection ourselves, preserving the original port
    # contract. An external plan cannot supply an unchecked output adapter.
    text=files['word_candidate'].read_text();require('__cec_embedding' not in text,'adapter name collision')
    require(len(re.findall(r'\bmodule\b',re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)))==1,'single word module required')
    text,count=re.subn(r'\bmodule\s+top\b','module __cec_embedding_word',text);require(count==1,'one word top required')
    lines=[text,'module top('+','.join(p[0] for p in source)+');']
    for n,d,w,_,_ in source:lines.append(f'{d} '+(f'[{w-1}:0] ' if w>1 else '')+n+';')
    lines.append(f'wire [{wide_width-1}:0] __cec_embedding_bits;')
    connections=[f'.{p[0]}({p[0]})' for p in inputs]+[f'.{wide_name}(__cec_embedding_bits)']
    lines.extend(['__cec_embedding_word model('+','.join(connections)+');',
                  f'assign {name}=__cec_embedding_bits[{wide_width-1}:{low}];','endmodule'])
    projection=out/'projected_word.v';projection.write_text('\n'.join(lines)+'\n')
    sat(files['candidate'],projection,out/'retained_candidate_bridge',timeout,checker)
    require(all(sha(p)==plan[k]['sha256'] for k,p in files.items()) and sha(__file__)==version,'source/verifier changed')
    return {'status':'pass','strict':True,'equivalent':True,'all_original_inputs_free':True,
        'all_original_outputs_compared':True,'original_input_bits':len(pi),'original_output_bits':width,
        'reference':plan['reference'],'candidate':plan['candidate'],'embedding':plan,
        'verifier_sha256':version,'scope':'All original inputs and outputs; no assumption about the discarded low bits.'}


def main():
    require(__debug__,'python -O cannot certify');p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=180);p.add_argument('--term-cap',type=int,default=300000)
    a=p.parse_args();require(a.timeout>0 and a.term_cap>0,'positive budgets required');a.out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    try:r=verify(a.plan.resolve(),a.out.resolve(),a.timeout,a.term_cap)
    except Exception as e:r={'status':'unknown','strict':False,'equivalent':None,'reason':f'{type(e).__name__}: {e}'}
    r['seconds']=time.monotonic()-start;save(a.out/'result.json',r);print(json.dumps(r,sort_keys=True));return 0 if r.get('equivalent') is True else 1


if __name__=='__main__':sys.exit(main())

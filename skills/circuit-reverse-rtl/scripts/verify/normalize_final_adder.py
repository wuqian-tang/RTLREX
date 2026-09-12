#!/usr/bin/env python3
"""Propose an explicit compressor/ripple output and strictly verify the rewrite.

Plan contains reference:{path,sha256}, output_name, cutnames, weights, constant.
Weights must be signed powers of two modulo the output width. The plan is an
untrusted affine-cone hypothesis. A complete original-to-rewritten CEC is
mandatory; a successful free-cut/discovery experiment alone cannot certify it.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time

if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify.algebraic.certificate import parse_primitive, source_contract
from verify.tooling import load_plan
from verify.composition import require, sha, save, sat


def normalize(plan_path,out,timeout):
    version=sha(__file__);plan=load_plan(plan_path);record=plan['reference']
    source=Path(record['path']).resolve();require(sha(source)==record['sha256'],'reference hash mismatch')
    gates,inputs,outputs,constants=parse_primitive(source);contract=source_contract(source)
    word=plan['output_name'];require(word in outputs,'unknown output word')
    width=len(outputs[word]);mod=1<<width;names=plan['cutnames'];weights=plan['weights']
    require(names and len(names)==len(weights) and len(set(names))==len(names),'invalid cuts/weights')
    require(all(n in gates or n in inputs for n in names),'unknown cut signal')
    require(type(plan['constant']) is int,'integral constant required')
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',source.read_text(),flags=re.S)
    prefix='__cec_ripple_';require(prefix not in text,'normalizer name collision')
    heaps=[[] for _ in range(width)];wires=[];ops=[]
    def node():
        n=prefix+str(len(wires));wires.append(n);return n
    def gate(op,target,args):ops.append(f'{op} {prefix}g{len(ops)}('+','.join([target,*args])+');')
    def fa(a,b,c):
        p,s,ab,ac,bc,t,carry=[node() for _ in range(7)]
        for op,target,args in [('xor',p,[a,b]),('xor',s,[p,c]),('and',ab,[a,b]),('and',ac,[a,c]),('and',bc,[b,c]),('or',t,[ab,ac]),('or',carry,[t,bc])]:gate(op,target,args)
        return s,carry
    constant=plan['constant']
    for n,w in zip(names,weights):
        require(type(w) is int,'integral weights required');w%=mod
        if not w:continue
        w=w if w<=mod//2 else w-mod;k=abs(w)
        require(k&(k-1)==0,'only signed power-of-two weights supported')
        bit=k.bit_length()-1
        if w<0:
            inv=node();gate('not',inv,[n]);n=inv;constant-=1<<bit
        heaps[bit].append(n)
    constant%=mod
    for bit in range(width):
        if constant>>bit&1:heaps[bit].append("1'b1")
        while len(heaps[bit])>2:
            z,c=fa(*[heaps[bit].pop() for _ in range(3)]);heaps[bit].append(z)
            if bit+1<width:heaps[bit+1].append(c)
    carry="1'b0"
    for bit in range(width):
        values=heaps[bit]+["1'b0"]*(2-len(heaps[bit]));z,carry=fa(*values,carry);gate('buf',outputs[word][bit],[z])
    # Preserve original logic behind a private name, including any fanout into
    # other outputs. Only the selected port receives the new ripple drivers.
    old=prefix+'original_word'
    text=re.sub(r'\b'+re.escape(word)+r'\b',old,text)
    text=re.sub(r'\bmodule\s+top\s*\([^;]*;', '', text, count=1)
    text=re.sub(r'\b(?:input|output)\b[^;]*;', '', text)
    head=['module top('+','.join(c[0] for c in contract)+');']
    for n,d,w,_,_ in contract:head.append(f'{d} '+(f'[{w-1}:0] ' if w>1 else '')+n+';')
    head.append('wire '+(f'[{width-1}:0] ' if width>1 else '')+old+';')
    # A proposed cut may itself refer to the replaced output word.
    require(all(not re.match(re.escape(word)+r'(?:\[|$)',n) for n in names),'output cannot be its own affine cut')
    text='\n'.join(head)+'\n'+text.replace('endmodule','\n'.join(['wire '+n+';' for n in wires]+ops)+'\nendmodule')
    target=out/'rewritten.v';target.write_text(text);save(out/'plan.json',plan)
    proof=sat(source,target,out/'full_bridge',timeout,Path(__file__).with_name('cec.py'))
    require(sha(source)==record['sha256'] and sha(__file__)==version,'source or normalizer changed')
    return {'status':'pass','strict':True,'equivalent':True,'all_original_outputs_compared':True,
        'reference':record,'candidate':{'path':str(target),'sha256':sha(target)},
        'output_name':word,'cut_count':len(names),'verifier_sha256':version,'bridge':proof}


def main():
    require(__debug__,'python -O cannot certify');p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--timeout',type=int,default=120)
    a=p.parse_args();require(a.timeout>0,'positive timeout required');a.out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    try:r=normalize(a.plan.resolve(),a.out.resolve(),a.timeout)
    except Exception as e:r={'status':'unknown','strict':False,'equivalent':None,'reason':f'{type(e).__name__}: {e}'}
    r['seconds']=time.monotonic()-start;save(a.out/'result.json',r);print(json.dumps(r,sort_keys=True));return 0 if r.get('equivalent') is True else 1


if __name__=='__main__':sys.exit(main())

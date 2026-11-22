#!/usr/bin/env python3
"""Exact CEC through hash-bound intermediate RTLs.

Plan: {nodes:[{path,sha256},...], edges:[{engine, ...}, ...]}.
Every adjacent pair has the same complete interface. Intermediates are proof
hypotheses, never assumptions or replacements for the original endpoints.
"""
import argparse
import json
from pathlib import Path
import sys
import time

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify.composition import require, sha, save, run_command
from verify.cec import parse_top_port_contract


def verify(plan_path, out, timeout, cap):
    verifier_hash=sha(__file__)
    plan = json.loads(plan_path.read_text())
    require(plan.get('schema') == 'exact-rtl-chain/v1', 'unknown chain schema')
    records = plan['nodes']; edges = plan['edges']
    require(len(records) >= 2 and len(edges) == len(records)-1, 'every adjacent edge is required')
    nodes = [Path(r['path']).resolve() for r in records]
    for p,r in zip(nodes,records): require(p.is_file() and sha(p)==r['sha256'], 'chain node hash mismatch')
    contracts = [parse_top_port_contract(p) for p in nodes]
    require(contracts[0] and all(c == contracts[0] for c in contracts), 'chain interfaces differ')
    require(any(p.direction == 'output' for p in contracts[0]), 'no original outputs')
    save(out/'plan.json',plan); results=[]
    for i,edge in enumerate(edges):
        engine=edge['engine']
        require(engine in ('auto','smt','sat-bits','sat-lemmas','algebraic','algebraic-cones'), 'unsupported exact edge engine')
        folder=out/f'edge_{i:02d}'
        command=[sys.executable,str(Path(__file__).with_name('cec.py')),str(nodes[i]),str(nodes[i+1]),
                 '--engine',engine,'--strict-cec','--keep-tmp','--tmpdir',str(folder),
                 '--timeout',str(timeout),'--abc-timeout',str(timeout),'--smt-timeout',str(timeout),
                 '--sat-total-timeout',str(timeout),'--algebraic-timeout',str(timeout),
                 '--algebraic-term-cap',str(cap),'--json']
        for name in edge.get('sliced_outputs',[]): command.extend(['--algebraic-sliced-output',name])
        for bit in edge.get('case_split_bits',[]): command.extend(['--algebraic-case-split-bit',bit])
        text=run_command(command,folder,10*timeout+60)
        result=json.loads(text)
        require(result.get('status')=='pass' and result.get('equivalent') is True,
                'incomplete or inconclusive chain edge')
        save(folder/'result.json',result)
        results.append({'edge':i,'engine':engine,'result_path':str(folder/'result.json'),
                        'result_sha256':sha(folder/'result.json')})
    for p,r in zip(nodes,records):require(sha(p)==r['sha256'],'chain node changed during proof')
    require(sha(__file__)==verifier_hash,'chain verifier changed during proof')
    return {'status':'pass','equivalent':True,'strict':True,'all_original_outputs_compared':True,
            'all_original_inputs_free':True,'reference':records[0],'candidate':records[-1],
            'nodes':records,'edges':results,'complete_interface':[vars(p) for p in contracts[0]],
            'verifier_sha256':verifier_hash}


def main():
    require(__debug__, 'python -O cannot certify')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=180);p.add_argument('--term-cap',type=int,default=1000000)
    a=p.parse_args();require(a.timeout>0 and a.term_cap>0,'positive budgets required')
    a.out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    try: result=verify(a.plan.resolve(),a.out.resolve(),a.timeout,a.term_cap)
    except Exception as exc:result={'status':'unknown','strict':False,'equivalent':None,'reason':f'{type(exc).__name__}: {exc}'}
    result['seconds']=time.monotonic()-start;save(a.out/'result.json',result)
    print(json.dumps(result,sort_keys=True));return 0 if result.get('equivalent') is True else 1


if __name__=='__main__':sys.exit(main())

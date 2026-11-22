#!/usr/bin/env python3
"""Check published terminal artifacts; optionally recompute Q or recheck RTL.

Historical outcomes are never overwritten. Fresh equivalence uses the installed
portable checker, not a claim of identical historical execution.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(ok, message):
    if not ok:
        raise ValueError(message)

def check_inventory(directory, expected):
    actual={p.relative_to(directory).as_posix() for p in directory.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    require(actual==set(expected),
            f'{directory.name}: inventory mismatch; extra={sorted(actual-set(expected))}, missing={sorted(set(expected)-actual)}')

def check_record(root, row, published):
    label=f"{row['case']}/{row['arm']}"
    for key in ('case','arm','input_sha256'):
        require(row[key] == published[key], f'{label}: {key} mismatch')
    require(row['candidate_sha256'] == (published['candidate_sha256'] or None), f'{label}: terminal identity mismatch')
    require(bool(row['candidate']) == bool(row['candidate_sha256']), f'{label}: missing terminal file')
    for key in ('V','H'):
        require(row[key] == (published[key]=='True'), f'{label}: published {key} changed')
    q=int(published['syntax_cost']) if published['syntax_cost'] else None
    require(row['Q']==q, f'{label}: published Q changed')
    for path_key, hash_key in (('candidate','candidate_sha256'),('receipt','receipt_sha256'),('prompt','prompt_sha256')):
        if row[path_key]:
            p=(root/row[path_key]).resolve()
            require(p.is_relative_to(root.resolve()),f'{label}: artifact escapes package')
            require(p.is_file() and sha(p)==row[hash_key], f'{label}: {path_key} hash mismatch')
    receipt=json.loads((root/row['receipt']).read_text())
    for key in ('case','arm','input_sha256','candidate_sha256','prompt_sha256'):
        require(receipt[key]==row[key],f'{label}: receipt {key} mismatch')
    for key in ('V','H','Q'):
        require(receipt['published_'+key]==row[key],f'{label}: receipt {key} mismatch')
    require(receipt['terminal_candidate_available']==bool(row['candidate']),f'{label}: receipt terminal mismatch')
    require(not row['V'] or (bool(row['candidate']) and receipt['evaluation_target_is_terminal']),f'{label}: diagnostic candidate cannot establish V')

def check_all():
    rows=json.loads((ROOT/'artifacts.json').read_text())['records']
    with (ROOT/'case_results.csv').open(newline='') as f:
        published={(r['case'],r['arm']):r for r in csv.DictReader(f)}
    keys=[(r['case'],r['arm']) for r in rows]
    require(len(keys)==200 and len(set(keys))==200 and set(keys)==set(published),'Artifact coverage mismatch')
    check_inventory(ROOT/'rtl', {str(Path(r['candidate']).relative_to('rtl')) for r in rows if r['candidate']})
    for row in rows:
        check_record(ROOT,row,published[row['case'],row['arm']])
        truth=REPO/'benchmarks/tt100/truth'/f"{row['case']}.truth"
        require(sha(truth)==row['input_sha256'],f"{row['case']}: input hash mismatch")
    metadata=json.loads((ROOT/'metadata.json').read_text())
    for filename,key in [('RTL_cost_calculator.py','calculator_sha256'),('syntax_cost.csv','weights_sha256')]:
        require(sha(ROOT/'scoring'/filename)==metadata['cost'][key],f'Frozen scorer mismatch: {filename}')
    original=ROOT/'protocol/evaluated_skill_original_manifest.json'
    require(sha(original)==metadata['frozen_skill_manifest_sha256'],'Original Skill manifest mismatch')
    export=json.loads((ROOT/'protocol/evaluated_skill_export.json').read_text())
    omitted={r['path']:r['sha256'] for r in export['omitted']}
    expected={r['path']:r['sha256'] for r in json.loads(original.read_text())}
    require(set(omitted)=={'scripts/tool_paths.env','scripts/sampling/fast_primitive_sampler'},'Unexpected frozen Skill omissions')
    check_inventory(ROOT/'evaluated_skill', set(expected)-set(omitted))
    for name,digest in expected.items():
        if name in omitted:
            require(omitted[name]==digest,'Omitted identity mismatch')
            require(not (ROOT/'evaluated_skill'/name).exists(),'Omitted local file unexpectedly exported')
        else:require(sha(ROOT/'evaluated_skill'/name)==digest,f'Frozen Skill mismatch: {name}')
    return rows

def scorer():
    spec=importlib.util.spec_from_file_location('rtlrex_frozen_final_scorer',ROOT/'scoring/RTL_cost_calculator.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    module.set_operator_cost_csv(str(ROOT/'scoring/syntax_cost.csv'))
    return module

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--score',action='store_true',help='Recompute Q for every selected terminal with a published Q')
    parser.add_argument('--recheck',action='store_true',help='Fresh complete-domain RTL validation; requires --out')
    parser.add_argument('--cases',nargs='+',help='Select case IDs, e.g. ex200 ex255')
    parser.add_argument('--arm',choices=['with_skill','no_skill'])
    parser.add_argument('--out',type=Path,help='New directory for fresh checks; never overwrites published results')
    parser.add_argument('--yosys',type=Path)
    args=parser.parse_args()
    if args.recheck and args.out is None:parser.error('--recheck requires a new --out directory')
    rows=check_all()
    selected=[r for r in rows if (not args.cases or r['case'] in args.cases) and (not args.arm or r['arm']==args.arm)]
    if args.cases:require(set(args.cases)<=set(r['case'] for r in rows),'Unknown case ID')
    report={'artifact_records_checked':len(rows),'terminal_files':sum(bool(r['candidate']) for r in rows),'validated_terminal_files':sum(r['V'] for r in rows),'score_checks':0,'fresh_validation':[]}
    if args.score:
        cost=scorer()
        for row in selected:
            if row['Q'] is not None:
                actual=cost.evaluate_rtl(str(ROOT/row['candidate']))[0]
                require(actual==row['Q'],f"{row['case']}/{row['arm']}: Q {actual} != {row['Q']}")
                report['score_checks']+=1
    unexpected=[]
    if args.recheck:
        args.out.mkdir(parents=True,exist_ok=False)
        sys.path.insert(0,str(REPO/'skills/circuit-reverse-rtl/scripts'))
        from verify.truth_yosys import verify,default_yosys
        yosys=args.yosys or default_yosys()
        for row in selected:
            if not row['candidate']:continue
            result=verify(REPO/'benchmarks/tt100/truth'/f"{row['case']}.truth",ROOT/row['candidate'],yosys,use_cache=False)
            target=args.out/f"{row['case']}-{row['arm']}.json"
            target.write_text(json.dumps(result,indent=2)+'\n')
            item={'case':row['case'],'arm':row['arm'],'historical_V':row['V'],'fresh_status':result['status']}
            report['fresh_validation'].append(item)
            print(json.dumps(item),flush=True)
            if row['V'] and result['status']!='pass':unexpected.append(item)
        (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return int(bool(unexpected))

if __name__=='__main__':
    raise SystemExit(main())

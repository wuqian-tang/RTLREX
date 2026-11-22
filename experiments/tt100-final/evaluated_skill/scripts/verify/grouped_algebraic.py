#!/usr/bin/env python3
"""Strict complete algebraic case cover from an explicit, hash-bound group plan.

This checker validates pure substitutions of selected input vector bits, then
independently replays every group's complete local Boolean cube. It constructs
no unproved input assumption. Plan discovery is separate. Current source scope:
primitive reference plus one flat, explicit wire/assign candidate module;
fixed ports must occur only through explicit individual bit references.
"""
import argparse,itertools,json,re,sys,time,concurrent.futures
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify.composition import require,sha,save,run_command
from verify.algebraic import certificate


def pinned(record):
    path=Path(record['path']).resolve();require(path.is_file() and sha(path)==record['sha256'],'artifact hash mismatch: '+str(path));return path


def bitsafe_sources(reference,candidate,fixed_bits):
    """Rule out lexical scopes, whole-bus uses and edits to input drivers."""
    contract=certificate.source_contract(reference)
    require(contract==certificate.source_contract(candidate),'source interfaces differ')
    gates,inputs,outputs,constants=certificate.parse_primitive(reference)
    require(not(set(gates)&inputs),'primitive reference drives an input')
    require(not(set(gates)&set(constants)),'primitive reference drives a literal constant')
    require(set(fixed_bits)<=inputs,'fixed bits must be original inputs')
    fixed_ports={}
    for bit in fixed_bits:
        match=re.fullmatch(r'(\w+)\[(\d+)\]',bit)
        require(match is not None,'outer fixed bits must be explicit vector bits')
        fixed_ports[match[1]]=next(c[2] for c in contract if c[0]==match[1] and c[1]=='input')
    for source in [reference,candidate]:
        text=re.sub(r'/\*.*?\*/|//[^\n]*','',source.read_text(),flags=re.S)
        require('`' not in text and '\\' not in text and '(*' not in text and chr(34) not in text,'macros, escaped names, attributes and strings unsupported')
        body=[]
        for statement in text.split(';'):
            s=statement.strip()
            if not s or s=='endmodule' or re.match(r'^(module|input|output)\b',s):continue
            if re.match(r'^wire\b',s):
                require(re.fullmatch(r'wire\s+(?:signed\s+)?(?:\[\s*\d+\s*:\s*\d+\s*\]\s*)?\w+(?:\s*,\s*\w+)*',s) is not None,'only flat wire declarations supported');continue
            if source==candidate:
                match=re.fullmatch(r'assign\s+(\w+)(?:\[\s*\d+(?:\s*:\s*\d+)?\s*\])?\s*=\s*(.+)',s)
                require(match is not None,'candidate must contain only explicit wire/assign statements')
                require(match[1] not in {c[0] for c in contract if c[1]=='input'},'candidate drives an input')
                s=match[2]
            body.append(s)
        usage=';'.join(body)
        for port,width in fixed_ports.items():
            pattern=r'(?<![\w$])'+re.escape(port)+r'\s*\[\s*(\d+)\s*\]'
            for found in re.finditer(pattern,usage):require(int(found[1])<width,'input bit outside declared range')
            rest=re.sub(pattern,'0',usage)
            require(re.search(r'(?<![\w$])'+re.escape(port)+r'(?![\w$])',rest) is None,'fixed port is used as a whole bus or part-select')
    return contract,inputs,outputs


def substitute(text,assignment):
    for bit,value in assignment.items():
        port,index=re.fullmatch(r'(\w+)\[(\d+)\]',bit).groups()
        text=re.sub(r'(?<![\w$])'+re.escape(port)+r'\s*\[\s*'+index+r'\s*\]',f"1'b{value}",text)
    return text


def validate_plan(plan):
    require(plan.get('schema')=='exact-grouped-algebraic/v1','unknown plan schema')
    reference=pinned(plan['reference']);candidate=pinned(plan['candidate']);fixed=plan['fixed_bits'];groups=plan['groups']
    require(len(fixed)==len(set(fixed)) and len(fixed)<=12,'duplicate or excessive fixed bits')
    contract,inputs,outputs=bitsafe_sources(reference,candidate,fixed)
    require(len(groups)==1<<len(fixed),'incomplete outer case count');covered=set();prepared=[]
    for group in groups:
        assignment=group['assignment'];require(set(assignment)==set(fixed) and all(type(x)is int and x in (0,1) for x in assignment.values()),'invalid outer assignment')
        key=tuple(assignment[x] for x in fixed);require(key not in covered,'duplicate outer assignment');covered.add(key)
        ref=pinned(group['reference']);cand=pinned(group['candidate']);identities=pinned(group['identities'])
        require(ref.read_text()==substitute(reference.read_text(),assignment) and cand.read_text()==substitute(candidate.read_text(),assignment),'group contains edits beyond the exact input cofactor')
        require(certificate.source_contract(ref)==contract and certificate.source_contract(cand)==contract,'group interface changed')
        splits=group.get('split_bits',[]);require(len(splits)==len(set(splits)) and len(splits)<=8 and set(splits)<=inputs and not(set(splits)&set(fixed)),'invalid inner split bits')
        idata=json.loads(identities.read_text());require(Path(idata['source_path']).resolve()==ref,'identity source mismatch')
        prepared.append({'reference':str(ref),'candidate':str(cand),'identities':str(identities),'assignment':assignment,'split_bits':splits,'outputs':list(outputs)})
    require(covered==set(itertools.product((0,1),repeat=len(fixed))),'incomplete outer Boolean cube')
    return reference,candidate,contract,prepared


def replay(job):
    item={'input_path':job['reference'],'candidate_path':job['candidate'],'input_sha256':sha(job['reference']),'candidate_sha256':sha(job['candidate'])}
    splits=job['split_bits'];cases=[dict(zip(splits,values)) for values in itertools.product((0,1),repeat=len(splits))]
    return certificate.verify(item,Path(job['identities']),Path(job['out']),yosys=Path(job['yosys']),term_cap=job['term_cap'],trim_constant_high_zero=False,sliced_outputs=job['outputs'],case_splits=cases)


def verify(plan_path,out,yosys,timeout,cap,jobs):
    plan=json.loads(plan_path.read_text());reference,candidate,contract,groups=validate_plan(plan);save(out/'plan.json',plan)
    dependencies=[reference,candidate,yosys,Path(__file__),Path(__file__).with_name('composition.py'),Path(__file__).with_name('cec.py'),*Path(certificate.__file__).parent.glob('*.py')]
    frozen={str(p):sha(p) for p in dependencies}
    for group in groups:
        for key in ['reference','candidate','identities']:frozen[group[key]]=sha(group[key])
    def one(index):
        group=groups[index];folder=out/f'group_{index:04d}';folder.mkdir();job={**group,'out':str(folder/'independent_replay'),'yosys':str(yosys),'term_cap':cap};save(folder/'job.json',job)
        run_command([sys.executable,str(Path(__file__).resolve()),'--replay-worker',str(folder/'job.json')],folder/'execution',timeout)
        record=folder/'independent_replay/record.json';r=json.loads(record.read_text())
        require(r['status']=='strict_algebraic_equivalence' and r['all_original_outputs_compared'] is True and r['all_final_variables_are_primary_inputs'] is True,'group replay did not cover all outputs')
        return {'assignment':group['assignment'],'split_bits':group['split_bits'],'replay':{'path':str(record),'sha256':sha(record)}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:records=list(ex.map(one,range(len(groups))))
    require(all(sha(p)==h for p,h in frozen.items()),'source/checker changed during grouped replay')
    return {'status':'pass','strict':True,'equivalent':True,'all_original_inputs_free':True,'all_original_outputs_compared':True,'reference':plan['reference'],'candidate':plan['candidate'],'source_interface_contract':contract,'outer_fixed_bits':plan['fixed_bits'],'outer_group_count':len(groups),'complete_outer_boolean_cube':True,'total_leaf_assignments':sum(1<<len(g['split_bits']) for g in groups),'groups':records,'source_hashes':frozen,'scope':'Exactly the supplied original source pair over every primary-input assignment; no original-circuit binding is implied for a projected or conditional input pair.'}


def main():
    require(__debug__,'python -O cannot certify')
    if len(sys.argv)>1 and sys.argv[1]=='--replay-worker':
        result=replay(json.loads(Path(sys.argv[2]).read_text()));print(result['status']);return 0
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--yosys',type=Path,default=certificate.ROOT/'external/yosys/yosys');p.add_argument('--timeout',type=int,default=300,help='total watchdog seconds for each independent group replay');p.add_argument('--term-cap',type=int,default=300000);p.add_argument('--jobs',type=int,default=1);a=p.parse_args();require(a.timeout>0 and a.term_cap>0 and 1<=a.jobs<=8,'invalid budgets');a.out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    try:r=verify(a.plan.resolve(),a.out.resolve(),a.yosys.resolve(),a.timeout,a.term_cap,a.jobs)
    except Exception as e:r={'status':'unknown','strict':False,'equivalent':None,'reason':type(e).__name__+': '+str(e)}
    r['seconds']=time.monotonic()-start;save(a.out/'result.json',r);print(json.dumps(r,sort_keys=True));return 0 if r.get('strict') else 1
if __name__=='__main__':raise SystemExit(main())

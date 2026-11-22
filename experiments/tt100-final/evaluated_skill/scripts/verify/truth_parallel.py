"""Validation-only exhaustive interleaved Icarus replay prototype."""
from __future__ import annotations
import hashlib, os
from pathlib import Path
import re, shutil, signal, subprocess, sys, tempfile, time, threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from truth.utils import read_truth_words

def sha(data):return hashlib.sha256(data).hexdigest()

def validate_partitions(records, vectors, workers):
    if any(any(not isinstance(r.get(k),int) or isinstance(r.get(k),bool)
                   for k in ['offset','stride','count','first','last']) for r in records):return False
    if len(records)!=workers or {r.get('offset') for r in records}!=set(range(workers)):return False
    for r in records:
        o=r['offset'];count=max(0,(vectors-1-o)//workers+1)
        if (r.get('status')!='pass' or r.get('stride')!=workers or r.get('count')!=count
            or r.get('first')!=(o if count else -1)
            or r.get('last')!=(o+(count-1)*workers if count else -1)):return False
    return sum(r['count'] for r in records)==vectors

def run_one(truth,verilog,input_port,output_port,compile_timeout,run_timeout,*,workers=None):
    started=time.monotonic();truth=Path(truth);verilog=Path(verilog)
    truth_bytes=truth.read_bytes();rtl_bytes=verilog.read_bytes()
    rows=[line.strip() for line in truth_bytes.decode().splitlines() if line.strip()]
    if (not rows or len(rows[0])<2 or len(rows[0])&(len(rows[0])-1)
        or any(len(row)!=len(rows[0]) or set(row)-{'0','1'} for row in rows)):
        return {'status':'invalid_truth'}
    N=len(rows[0]);n=N.bit_length()-1;m=len(rows)
    if n>20:return {'status':'unsupported_domain','n_inputs':n}
    expected=[sum(int(row[(~x)&(N-1)])<<j for j,row in enumerate(rows)) for x in range(N)]
    if workers is None:workers=1 if n<12 else 4
    if not isinstance(workers,int) or isinstance(workers,bool) or not 1<=workers<=4:return {'status':'invalid_workers','workers':workers}
    K=min(workers,N)
    result={'truth':str(truth),'verilog':str(verilog),'n_inputs':n,'n_outputs':m,'vectors':N,
        'workers_requested':workers,'workers':K,'partitions':[],
        'truth_sha256':sha(truth_bytes),'candidate_sha256':sha(rtl_bytes),
        'checker_sha256':sha(Path(__file__).read_bytes()),
        'verification_method':'complete-domain interleaved Icarus Verilog replay',
        'coverage':{'index_domain':[0,N-1],'offsets':list(range(K)),'stride':K,
            'partition_rule':'x=offset+t*stride for t>=0 and x<vectors',
            'expected_counts':[max(0,(N-1-o)//K+1) for o in range(K)],
            'disjoint_residue_classes':True,'coverage_valid':False},
        'deadline_policy':'single shared replay deadline after compilation',
        'shared_replay_timeout_seconds':run_timeout,'cache_enabled':False}
    iverilog=shutil.which('iverilog');vvp=shutil.which('vvp')
    if not iverilog or not vvp:return {**result,'status':'tool_missing'}
    result['tool_binary_sha256']={name:sha(Path(path).read_bytes()) for name,path in [('iverilog',iverilog),('vvp',vvp)]}
    with tempfile.TemporaryDirectory(prefix='parallel_truth_') as directory:
        d=Path(directory);rtl=d/'candidate.v';rtl.write_bytes(rtl_bytes)
        values=d/'expected.mem';values.write_text(''.join(f'{v:0{m}b}\n' for v in expected))
        sim=d/'simv';tb=d/'tb.v'
        tb.write_text(f'''module tb;
reg [{n-1}:0] {input_port}; wire [{m-1}:0] {output_port};
reg [{m-1}:0] expected[0:{N-1}];
integer offset,stride,index,count,first,last;
top dut(.{input_port}({input_port}),.{output_port}({output_port}));
initial begin
 if (!$value$plusargs("OFFSET=%d",offset) || !$value$plusargs("STRIDE=%d",stride)) begin $display("PARTITION_INVALID_ARGS"); $finish; end
 if (offset<0 || offset>={K} || stride!={K}) begin $display("PARTITION_INVALID_ARGS"); $finish; end
 $readmemb("{values}",expected);
 count=0; first=-1; last=-1;
 for(index=offset;index<{N};index=index+stride) begin
  {input_port}=index; #1;
  if({output_port} !== expected[index]) begin
   $display("PARTITION_MISMATCH offset=%0d stride=%0d index=%0d got=%b expected=%b",offset,stride,index,{output_port},expected[index]); $finish;
  end
  if(count==0)first=index; last=index; count=count+1;
 end
 $display("PARTITION_PASS offset=%0d stride=%0d count=%0d first=%0d last=%0d",offset,stride,count,first,last);
 $finish;
end
endmodule
''')
        result.update(tb_sha256=sha(tb.read_bytes()),tb_source=tb.read_text(),expected_sha256=sha(values.read_bytes()))
        command=[iverilog,'-g2012','-s','tb','-o',str(sim),str(rtl),str(tb)];cs=time.monotonic()
        try:r=subprocess.run(command,capture_output=True,text=True,timeout=compile_timeout)
        except subprocess.TimeoutExpired:return {**result,'status':'compile_timeout','compile_wall_seconds':time.monotonic()-cs}
        result['compile']={'command':command,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'wall_seconds':time.monotonic()-cs}
        if r.returncode:return {**result,'status':'compile_fail'}
        result['simv_sha256']=sha(sim.read_bytes());rs=time.monotonic();deadline=rs+run_timeout;running=[];status='pass'
        old_handlers={}
        def cancelled(signum,frame):raise SystemExit(128+signum)
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM,signal.SIGINT):
                old_handlers[signum]=signal.getsignal(signum);signal.signal(signum,cancelled)
        try:
            for o in range(K):
                command=[vvp,str(sim),f'+OFFSET={o}',f'+STRIDE={K}']
                stdout=(d/f'worker{o}.stdout').open('w');stderr=(d/f'worker{o}.stderr').open('w')
                try:p=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=False)
                finally:stdout.close();stderr.close()
                running.append((o,p,command))
            while any(p.poll() is None for _,p,_ in running):
                if time.monotonic()>=deadline:status='run_timeout';break
                if any(p.poll() is not None and p.returncode!=0 for _,p,_ in running):status='run_fail';break
                time.sleep(min(0.01,max(0,deadline-time.monotonic())))
            if time.monotonic()>deadline and status=='pass':status='run_timeout'
        except Exception as error:status='run_fail';result['worker_error']=f'{type(error).__name__}: {error}'
        finally:
            # Trusted vvp inherits the verifier's process group, so outer killpg
            # reaches every worker. Local cleanup signals exact Popen children.
            blocked=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGTERM,signal.SIGINT}) if old_handlers else None
            try:
                for _,p,_ in running:
                    if p.poll() is None:p.terminate()
                for _,p,_ in running:
                    try:p.wait(timeout=1)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
            finally:
                for signum,old in old_handlers.items():signal.signal(signum,old)
                if blocked is not None:signal.pthread_sigmask(signal.SIG_SETMASK,blocked)
        for o,p,command in running:
            stdout=(d/f'worker{o}.stdout').read_text();stderr=(d/f'worker{o}.stderr').read_text()
            item={'offset':o,'stride':K,'command':command,'returncode':p.returncode,'stdout':stdout,'stderr':stderr,'status':'unknown'}
            mismatches=re.findall(r'PARTITION_MISMATCH offset=(\d+) stride=(\d+) index=(\d+) got=([01xXzZ]+) expected=([01xXzZ]+)',stdout)
            passes=re.findall(r'PARTITION_PASS offset=(\d+) stride=(\d+) count=(\d+) first=(-?\d+) last=(-?\d+)',stdout)
            if mismatches:
                offset,stride,index,got,want=mismatches[0];item.update(status='mismatch',index=int(index),got=got,expected=want)
                if status=='pass':status='mismatch'
            elif p.returncode==0 and len(passes)==1:
                offset,stride,count,first,last=map(int,passes[0])
                if offset==o and stride==K:item.update(status='pass',count=count,first=first,last=last)
            result['partitions'].append(item)
        valid=validate_partitions(result['partitions'],N,K);result['coverage']['coverage_valid']=valid
        if status=='pass' and not valid:status='coverage_fail'
        if truth.read_bytes()!=truth_bytes or verilog.read_bytes()!=rtl_bytes:status='input_changed'
        result.update(status=status,replay_wall_seconds=time.monotonic()-rs,proof_wall_seconds=time.monotonic()-started)
        return result

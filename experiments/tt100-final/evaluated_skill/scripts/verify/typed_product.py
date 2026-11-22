"""Exact modular certificate for two unsigned, directly wired product words.
The only output must be exactly the low prefix of one native $mul result.
Every operand bit must be an original PI bit or a Boolean constant. No gate
assumption, solver timeout acceptance, or value-range hypothesis is admitted.
"""
from pathlib import Path
import argparse,json,sys,time
if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify.algebraic.certificate import ROOT
R=ROOT
from verify.composition import sha,save,run_command
from verify.algebraic.certificate import source_contract

def canonical(source,folder,yosys=None):
 folder.mkdir();yosys=yosys or R/'external/yosys/yosys';j=folder/'word.json';cmd=[str(yosys),'-q','-p',f'read_verilog {source}; hierarchy -check -top top; proc -noopt; opt; check -assert; write_json {j}'];run_command(cmd,folder/'lower',30);m=json.loads(j.read_text())['modules']['top'];ports=m['ports'];outs=[p for p in ports.values() if p['direction']=='output'];assert len(outs)==1;bits=outs[0]['bits'];width=len(bits);assert width>0
 inputs={}
 for name,p in ports.items():
  assert not p.get('signed',False) and not p.get('offset',0) and not p.get('upto',False)
  if p['direction']=='input':
   for b,signal in enumerate(p['bits']):assert type(signal) is int and signal not in inputs;inputs[signal]=f'{name}[{b}]'
 choices=[c for c in m['cells'].values() if c['type']=='$mul' and c['connections']['Y'][:width]==bits];assert len(choices)==1,'one full product output prefix required';cell=choices[0];co=cell['connections'];assert len(co['Y'])>=width
 for name in ['A','B','Y']:assert int(cell['parameters'][name+'_WIDTH'],2)==len(co[name])
 for p in ['A_SIGNED','B_SIGNED']:assert int(cell['parameters'].get(p,'0'),2)==0,'unsigned product required'
 def operand(values):
  result={}
  for k,signal in enumerate(values):
   assert signal in inputs or signal in ['0','1'],'operand must be wired directly from primary inputs/constants'
   if signal=='0':continue
   term=() if signal=='1' else (inputs[signal],);result[term]=result.get(term,0)+(1<<k)
  return result
 a=operand(co['A']);b=operand(co['B']);mod=1<<width;poly={}
 for x,cx in a.items():
  for y,cy in b.items():
   term=tuple(sorted(set(x)|set(y)));poly[term]=(poly.get(term,0)+cx*cy)%mod
 poly={k:v for k,v in poly.items() if v}
 # Store JSON-compatible operand identities and the canonical modulo-ring result.
 data={'output_width':width,'native_product_width':len(co['Y']),'operand_a':[{'bits':k,'weight':v} for k,v in a.items()],'operand_b':[{'bits':k,'weight':v} for k,v in b.items()],'polynomial':[{'bits':k,'coefficient':v} for k,v in sorted(poly.items())],'word_json_sha256':sha(j)};save(folder/'canonical.json',data);return width,poly,data

def main():
 assert __debug__;p=argparse.ArgumentParser();p.add_argument('--left',type=Path,required=True);p.add_argument('--right',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--yosys',type=Path,default=R/'external/yosys/yosys');a=p.parse_args();a.out.mkdir(exist_ok=False);a.yosys=a.yosys.resolve();sourcehashes={str(q.resolve()):sha(q) for q in [a.left,a.right]};dependencies={str(q):sha(q) for q in [a.yosys,Path(__file__),Path(__file__).with_name('composition.py'),Path(__file__).with_name('cec.py'),Path(__file__).parent/'algebraic/certificate.py']};start=time.monotonic();result={'status':'unknown','strict':False,'equivalent':None}
 try:
  assert source_contract(a.left)==source_contract(a.right),'full source interface differs';w,l,li=canonical(a.left.resolve(),a.out/'left',a.yosys);rw,r,ri=canonical(a.right.resolve(),a.out/'right',a.yosys);assert w==rw and l==r,'nonzero modular difference';assert all(sha(Path(q))==h for q,h in sourcehashes.items());assert all(sha(Path(q))==h for q,h in dependencies.items());result={'status':'pass','strict':True,'equivalent':True,'all_original_inputs_free':True,'all_original_output_bits_compared':w,'source_hashes':sourcehashes,'checker_dependencies':dependencies,'native_widths':[li['native_product_width'],ri['native_product_width']],'canonical_terms':len(l),'theorem':'For unsigned operands a,b and native product width N>=W, low_W((a*b) mod 2^N)=(a*b) mod 2^W. Each directly wired operand is expanded exactly into weighted original Boolean PI bits; x*x=x. Both canonical polynomials match coefficientwise modulo2^W.','yosys_sha256':sha(a.yosys),'checker_sha256':sha(Path(__file__))}
 except Exception as e:result['reason']=type(e).__name__+': '+str(e)
 result['seconds']=time.monotonic()-start;save(a.out/'result.json',result);print(json.dumps(result));return 0 if result['strict'] else 1
if __name__=='__main__':raise SystemExit(main())

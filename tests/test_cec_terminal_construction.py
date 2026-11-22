"""Semantics and collision controls for native coefficient obligation emission."""
import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/circuit-reverse-rtl/scripts'))
from verify.algebraic_terminal import residual
class NativeCoefficientConstruction(unittest.TestCase):
 def test_native_names_bit_selects_and_exact_modular_cancellation(self):
  with tempfile.TemporaryDirectory() as td:
   d=Path(td);ref=d/'reference.v'
   ref.write_text('module top(a, out); input [1:0] a; output [2:0] out;\nwire terminal_certificate_xc0;\nxor g0(terminal_certificate_xc0,a[0],a[1]);\nand g1(out[0],a[0],a[1]);\nbuf g2(out[1],a[0]);\nbuf g3(out[2],a[1]);\nendmodule\n')
   # A synthetic replay record isolates the construction function: it is not
   # presented as an original-circuit equivalence certificate.
   record={'status':'exact_terminal_residual_replayed','declared_output_bits':3,'input_sha256':hashlib.sha256(ref.read_bytes()).hexdigest(),'polynomial':[{'variables':['a[0]','a[1]'],'coefficient':2},{'variables':['terminal_certificate_xc0'],'coefficient':2},{'variables':['out[0]'],'coefficient':6},{'variables':[],'coefficient':4}]}
   rp=d/'residual.json';rp.write_text(json.dumps(record));audit=residual.construct(ref,rp,{'a[0]','a[1]'},d)
   mapping=audit['native_gate_renaming'];self.assertEqual(mapping['terminal_certificate_xc0'],'terminal_certificate_xc0');self.assertNotEqual(mapping['out[0]'],'out[0]');self.assertEqual(len(set(mapping.values())),len(mapping))
   generated=(d/'coefficient_reference.v').read_text();self.assertIn('output [1:0] terminal_certificate_xxc0;',generated)
   expected=d/'expected.v';expected.write_text("module top(a, terminal_certificate_xxc0); input [1:0] a; output [1:0] terminal_certificate_xxc0; assign terminal_certificate_xxc0=2'd2+{1'b0,(a[0]^a[1])}; endmodule\n")
   command=[sys.executable,str(ROOT/'skills/circuit-reverse-rtl/scripts/verify/cec.py'),str(d/'coefficient_reference.v'),str(expected),'--engine','cec','--strict-cec','--timeout','20','--abc-timeout','20','--json']
   p=subprocess.run(command,capture_output=True,text=True,timeout=40);r=json.loads(p.stdout);self.assertEqual(r['status'],'pass',r)
   expected.write_text(expected.read_text().replace("2'd2+","2'd3+"));p=subprocess.run(command,capture_output=True,text=True,timeout=40);r=json.loads(p.stdout);self.assertEqual(r['status'],'fail',r)
if __name__=='__main__':unittest.main()

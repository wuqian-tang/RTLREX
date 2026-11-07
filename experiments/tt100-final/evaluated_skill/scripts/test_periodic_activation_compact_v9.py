"""Portable full-domain periodic control contracts and negative checks."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import time
import tempfile
import unittest

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPTS))
from truth.periodic_activation_compact_v9 import (compact_periodic_phase,
    phase_geometry_safe, compact_odd_saturation_guards,
    compact_sigmoid_endpoint_guards, linearize_normal_activation_pack,
    share_periodic_word_addition,compact_periodic_output_controls)
from truth.semantic_compact import compact_semantic_rtl
from reverse.truth_reverse import emit_fp16_tanh
from cost.RTL_cost_calculator import evaluate_rtl
from verify.truth_yosys import default_yosys, verify
YOSYS = default_yosys()
SHA = lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
OUT = None


def write_truth(path,words,width):
    mask=len(words)-1
    path.write_text('\n'.join(''.join(str((words[mask^x]>>b)&1) for x in range(len(words)))
                              for b in range(width))+'\n')


def phase_source(e,f,p,q,b,c):
    n=1+e+f;w=p+f+1
    return f"""module top(input [{n-1}:0] x, output reg [65:0] y);
  wire [{e-1}:0] exponent = x[{n-2}:{f}];
  wire [{f-1}:0] fraction = x;
  localparam [{p-1}:0] TWO_OVER_PI = {p}'h{c:x};
  localparam signed [63:0] ONE = 64'sd{1<<q};
  reg [{w-1}:0] prod, ipart, remainder, halfv, frac_wide;
  reg [1:0] quadrant;
  reg round_up;
  reg signed [63:0] fracq;
  integer shift_amt;
  always @(*) begin
    y=0;prod=0;ipart=0;remainder=0;halfv=0;frac_wide=0;
    quadrant=0;round_up=0;fracq=0;shift_amt=0;
    if(exponent == {e}'h{(1<<e)-1:x}) begin
      y=0;
    end else begin
      prod = {{{{{p}{{1'b0}}}}, 1'b1, fraction}} * {{{f+1}'d0, TWO_OVER_PI}};
      shift_amt = {b} - exponent;
      ipart = prod >> shift_amt;
      remainder = prod - (ipart << shift_amt);
      if (shift_amt <= {w}) begin
        halfv = {w}'d1 << (shift_amt - 1);
        round_up = (remainder > halfv) || ((remainder == halfv) && ipart[0]);
      end
      quadrant = ipart[1:0] + round_up;
      frac_wide = remainder >> (shift_amt - {q});
      if(round_up) fracq = $signed(frac_wide[63:0]) - ONE;
      else fracq = $signed(frac_wide[63:0]);
      y={{quadrant,fracq}};
    end
  end
endmodule
"""


def phase_oracle(x,e,f,p,q,b,c):
    """Exact rational quotient rounded by Python's independent ties-even."""
    exp=(x>>f)&((1<<e)-1)
    if exp==(1<<e)-1:return 0
    sig=(1<<f)+(x&((1<<f)-1));product=c*sig;shift=b-exp
    nearest=round(Fraction(product,1<<shift))
    fraction=Fraction(product,1<<(shift-q))-nearest*(1<<q)
    floor_fraction=fraction.numerator//fraction.denominator
    return ((nearest&3)<<64)+(floor_fraction&((1<<64)-1))


def odd_guard_source(e,f):
    n=1+e+f;bias=(1<<(e-1))-1;one=bias<<f
    small=(bias-1)<<f;sat=(bias+1)<<f;nan=((1<<e)-1)*(1<<f)+(1<<(f-1))
    return f"""module top(input [{n-1}:0] x, output reg [{n-1}:0] y);
  wire sign = x[{n-1}];
  wire [{e-1}:0] exponent = x[{n-2}:{f}];
  wire [{f-1}:0] fraction = x;
  wire [{n-2}:0] magnitude = x;
  function fp_eq;input signed [63:0] a,b;begin fp_eq=a==b;end endfunction
  function fp_ne;input signed [63:0] a,b;begin fp_ne=a!=b;end endfunction
  function fp_le;input signed [63:0] a,b;begin fp_le=a<=b;end endfunction
  function fp_ge;input signed [63:0] a,b;begin fp_ge=fp_le(b,a);end endfunction
  always @(*) begin
    y=0;
    if(fp_eq(exponent,{e}'h{(1<<e)-1:x})) begin
      if(fp_ne(fraction,0)) y={n}'h{nan:x};
      else y={{sign,{n-1}'h{one:x}}};
    end else if(fp_eq(exponent,0)) begin
      y={{sign,{n-1}'d0}};
    end else if(fp_le(magnitude,{n-1}'h{small:x})) begin
      y=x;
    end else if(fp_ge(magnitude,{n-1}'h{sat:x})) begin
      y={{sign,{n-1}'h{one:x}}};
    end else begin
      y=x;
    end
  end
endmodule
"""


def sigmoid_control_source(e,f):
    n=1+e+f;bias=(1<<(e-1))-1;one=bias<<f;half=(bias-1)<<f
    low=1<<f;high=(((1<<e)-1)<<f)-1;nan=high+1+(1<<(f-1))
    pt=2*low+1;nt=2*low-1;ps=(bias+2)*low;ns=ps+1
    def raw(s,l,h):return f"(sign == 1'b{s} && magnitude >= {n-1}'h{l:x} && magnitude <= {n-1}'h{h:x})"
    def typed(s,l,h):return f"fp_land(fp_land(fp_eq(sign, 1'b{s}), fp_ge(magnitude, {n-1}'h{l:x})), fp_le(magnitude, {n-1}'h{h:x}))"
    guards=[(0,low,pt,half),(0,ps,high,one),(1,low,nt,half),(1,ns,high,0)]
    branches=''.join(f" end else if ({typed(s,l,h)}) begin\n y={n}'h{out:x};\n" for s,l,h,out in guards)
    return f"""module top(input [{n-1}:0] x, output reg [{2*n-1}:0] y);
  wire sign=x[{n-1}];
  wire [{n-2}:0] magnitude=x;
  wire [{e-1}:0] exponent=x[{n-2}:{f}];
  reg [{f-1}:0] frac;
  reg [{e-1}:0] xe;
  reg xs;
  function fp_eq;input signed [63:0] a,b;begin fp_eq=a==b;end endfunction
  function fp_ne;input signed [63:0] a,b;begin fp_ne=a!=b;end endfunction
  function fp_le;input signed [63:0] a,b;begin fp_le=a<=b;end endfunction
  function fp_ge;input signed [63:0] a,b;begin fp_ge=fp_le(b,a);end endfunction
  function fp_land;input signed [63:0] a,b;begin fp_land=a&&b;end endfunction
  function [{n-1}:0] saturation;
    input s;
    begin if(s) saturation={n}'h0;else saturation={n}'h{one:x};end
  endfunction
  wire [{n-1}:0] kernel_x =
    ({raw(0,low,pt)} || {raw(0,ps,high)} || {raw(1,low,nt)} || {raw(1,ns,high)} ||
     (exponent == {e}'d0) || (exponent == {e}'d{(1<<e)-1})) ? {n}'h{one:x} : x;
  always @(*) begin
    y={n}'h{half:x};frac=x;xe=exponent;xs=sign;
    if(fp_eq(xe,{e}'h{(1<<e)-1:x})) begin
      if(fp_eq(frac,0)) y=saturation(xs);else y={n}'h{nan:x};
{branches}    end else if(fp_ne(xe,0)) begin
      y=x;
    end
    y={{kernel_x,y[{n-1}:0]}};
  end
endmodule
"""


class PeriodicActivationTests(unittest.TestCase):
    records=[]

    @classmethod
    def setUpClass(cls):
        global OUT
        cls.records = []
        cls.temporary = tempfile.TemporaryDirectory(prefix='periodic-activation-controls-')
        OUT = Path(cls.temporary.name)
        assert SHA(SCRIPTS/'cost/RTL_cost_calculator.py')=='685d655fe1bb6dadeb36921cb3da42de2791cc31b252ea86aeb3e5a8bbd5b014'
        assert SHA(SCRIPTS/'cost/syntax_cost.csv')=='65a0ff43df653831655cba564349ac536c755b53335d97ee3860f410bccbebc0'
        assert SHA(Path(sys.modules['verify.truth_yosys'].__file__))=='9af230bbb7f58926906890607d3b44a4b94a71f0d2780ea8d3d0ea4df7f58978'

    def check(self,label,truth,source,positive=True):
        path=OUT/(label+'.v');path.write_text(source);started=time.monotonic()
        result=verify(truth,path,YOSYS,use_cache=False,frontend_timeout=120,compile_timeout=120,run_timeout=180)
        cost,_,detail=evaluate_rtl(str(path))
        record={'label':label,'candidate_sha256':SHA(path),'truth_sha256':SHA(truth),
                'cost':cost,'detail':detail,'wall_seconds':time.monotonic()-started,
                'expected_pass':positive,'result':result}
        self.records.append(record)
        (OUT/(label+'.proof.json')).write_text(json.dumps(record,indent=2)+'\n')
        if positive:self.assertEqual(result['status'],'pass',(label,result))
        else:
            self.assertNotEqual(result['status'],'pass',(label,result))
            self.assertEqual(result['frontend'],'pass',(label,result))
            self.assertEqual(result['interface']['status'],'pass',(label,result))
            self.assertIn(result['status'],['mismatch','fail'],(label,result))

    def test_a_phase_nonbenchmark_complete_and_negatives(self):
        for e,f,p,q,b,c in [(3,2,12,6,20,4095),(4,3,20,10,25,667543),
                             (5,4,32,12,51,2734261103)]:
            source=phase_source(e,f,p,q,b,c)
            compact=compact_periodic_phase(source,exponent_bits=e,fraction_bits=f)
            self.assertNotEqual(source,compact)
            words=[phase_oracle(x,e,f,p,q,b,c) for x in range(1<<(1+e+f))]
            truth=OUT/f'phase_E{e}F{f}.truth';write_truth(truth,words,66)
            self.check(f'phase_E{e}F{f}',truth,compact)
            if e==3:
                narrow_sum = compact.replace("reg [63:0] phase_nearest_integer, phase_scaled_product;", "reg [14:0] clipped_sum; reg [63:0] phase_nearest_integer, phase_scaled_product;").replace("prod=0;", "prod=0;clipped_sum=0;").replace("phase_nearest_integer = (prod + (16'd1 << (shift_amt - 1))) >> shift_amt;", "clipped_sum = prod + (15'd1 << (shift_amt - 1)); phase_nearest_integer = clipped_sum >> shift_amt;")
                self.check('phase_missing_guard_bit',truth,narrow_sum,False)
                self.check('phase_wrong_rounding',truth,compact.replace('shift_amt - 1','shift_amt - 2'),False)
                self.assertEqual(compact_periodic_phase(source.replace("12'hfff","12'hffe"),exponent_bits=e,fraction_bits=f),source.replace("12'hfff","12'hffe"))
                self.assertEqual(compact_periodic_phase(source.replace('1\'b1, fraction','1\'b0, fraction'),exponent_bits=e,fraction_bits=f),source.replace('1\'b1, fraction','1\'b0, fraction'))
        self.assertFalse(phase_geometry_safe(constant=3,constant_bits=8,fraction_bits=3,exponent_bits=4,reduction_bias=18,phase_bits=6))

    def test_b_odd_guard_complete_formats_and_negative(self):
        for e,f in [(3,2),(4,3),(5,4)]:
            source=odd_guard_source(e,f);compact=compact_odd_saturation_guards(source,exponent_bits=e,fraction_bits=f)
            self.assertNotEqual(source,compact)
            n=1+e+f;bias=(1<<(e-1))-1;one=bias<<f;inf=((1<<e)-1)<<f;sat=(bias+1)<<f
            words=[]
            for x in range(1<<n):
                mag=x&((1<<(n-1))-1);sign=x&(1<<(n-1))
                words.append(inf+(1<<(f-1)) if mag>inf else sign if mag<(1<<f) else sign+one if mag>=sat else x)
            truth=OUT/f'odd_E{e}F{f}.truth';write_truth(truth,words,n)
            self.check(f'odd_E{e}F{f}',truth,compact)
            if e==3:self.check('odd_nan_boundary_negative',truth,compact.replace(str(inf+1),str(inf)),False)

    def test_c_pack_integer_exhaustive_formats(self):
        for e,f in [(3,2),(4,3),(5,10),(8,7)]:
            bias=(1<<(e-1))-1;mask=(1<<(e+f))-1
            for exponent in range(-(1<<e),1<<e):
                for sig in range(1<<f,(1<<(f+1))+1):
                    old=(((exponent+bias+(sig>>(f+1)))&((1<<e)-1))<<f)|(sig&((1<<f)-1))
                    self.assertEqual(old,((exponent+bias-1)*(1<<f)+sig)&mask)

    def test_d_sigmoid_full_independent_guard_contracts(self):
        for e,f in [(3,2),(4,3),(5,4)]:
            source=sigmoid_control_source(e,f)
            compact=compact_sigmoid_endpoint_guards(source,exponent_bits=e,fraction_bits=f)
            self.assertNotEqual(source,compact)
            n=1+e+f;bias=(1<<(e-1))-1;scale=1<<f;one=bias*scale;half=(bias-1)*scale
            inf=((1<<e)-1)*scale;words=[]
            for x in range(1<<n):
                sign=x>>(n-1);mag=x&(inf+scale-1);exp,frac=divmod(mag,scale)
                tiny=2*scale-1 if sign else 2*scale+1
                sat=(bias+2)*scale+sign
                old_tiny=scale<=mag<=tiny;old_sat=sat<=mag<inf
                special=exp==(1<<e)-1;daz=exp==0
                isolated=special or daz or old_tiny or old_sat
                kernel=one if isolated else x
                endpoint=(inf+scale//2 if frac else (0 if sign else one)) if special else half if daz or old_tiny else (0 if sign else one) if old_sat else x
                words.append((kernel<<n)+endpoint)
            truth=OUT/f'sigmoid_control_E{e}F{f}.truth';write_truth(truth,words,2*n)
            self.check(f'sigmoid_control_E{e}F{f}',truth,compact)
            if e==3:
                self.check('sigmoid_guard_isolation_negative',truth,compact.replace('activation_tiny || activation_saturated','activation_tiny'),False)
                self.check('sigmoid_sign_threshold_negative',truth,compact.replace("sign ? 5'h7 : 5'h9","sign ? 5'h9 : 5'h7"),False)

    def test_e_bad_typed_contracts_fail_closed(self):
        source=odd_guard_source(3,2)
        bads=[source.replace('input signed [63:0] a,b','input signed [62:0] a,b',1),
              source.replace('input signed [63:0] a,b','input [63:0] a,b',1),
              source.replace('fp_eq=a==b','fp_eq=a!=b'),
              source.replace('fp_le=a<=b','fp_le=a<b'),
              source.replace('fp_ne=a!=b','fp_ne=a==b')]
        for bad in bads:self.assertEqual(compact_odd_saturation_guards(bad,exponent_bits=3,fraction_bits=2),bad)
        source=sigmoid_control_source(3,2)
        for old,new in [('input signed [63:0] a,b','input signed [31:0] a,b'),
                        ('input signed [63:0] a,b','input [63:0] a,b'),
                        ('fp_land=a&&b','fp_land=a||b'),('fp_ge=fp_le(b,a)','fp_ge=fp_le(a,b)')]:
            bad=source.replace(old,new);self.assertEqual(compact_sigmoid_endpoint_guards(bad,exponent_bits=3,fraction_bits=2),bad)
        source=compact_semantic_rtl(emit_fp16_tanh('Generic activation'))
        self.assertEqual(linearize_normal_activation_pack(source,exponent_bits=5,fraction_bits=10),source)
        self.assertEqual(linearize_normal_activation_pack(source,exponent_bits=5,fraction_bits=10,rounded_interval=(0,2048)),source)
        for old,new in [('input signed [63:0] a, b','input signed [62:0] a, b'),
                        ('input signed [63:0] a, b','input [63:0] a, b'),
                        ('fp_add = a + b','fp_add = a - b')]:
            bad=source.replace(old,new);self.assertNotEqual(bad,source)
            self.assertEqual(linearize_normal_activation_pack(bad,exponent_bits=5,fraction_bits=10,rounded_interval=(1024,2048)),bad)
        # Explicitly exercise the nested 65-bit adder contract, independently
        # of whichever sharing candidate the current semantic emitter picks.
        source="""module top(input [15:0] x,output reg [15:0] y);
  reg signed [63:0] out_exp,bin_exp,rounded;
  function signed [63:0] fp_add;
    input signed [63:0] a,b;
    begin fp_add=semantic_add65(a,b);end
  endfunction
  function signed [64:0] semantic_add65;
    input signed [64:0] a,b;
    begin semantic_add65=a+b;end
  endfunction
  always @(*) begin
    bin_exp=0;rounded=1024;y=0;
    out_exp=fp_add(fp_add(bin_exp,15),rounded[11]);
    y[14:10]=out_exp[4:0];y[9:0]=rounded[9:0];
  end
endmodule
"""
        self.assertNotEqual(linearize_normal_activation_pack(source,exponent_bits=5,fraction_bits=10,rounded_interval=(1024,2048)),source)
        for old,new in [('input signed [64:0] a,b','input signed [63:0] a,b'),
                        ('input signed [64:0] a,b','input [64:0] a,b'),
                        ('function signed [64:0] semantic_add65','function signed [63:0] semantic_add65'),
                        ('semantic_add65=a+b','semantic_add65=a-b')]:
            bad=source.replace(old,new);self.assertNotEqual(bad,source)
            self.assertEqual(linearize_normal_activation_pack(bad,exponent_bits=5,fraction_bits=10,rounded_interval=(1024,2048)),bad)



    def test_g_periodic_word_sharing_full_formats_and_contracts(self):
        helper='  function signed [63:0] fp_add; input signed [63:0] a,b; begin fp_add=a+b;end endfunction\n'
        for e,f,p,q,b,c in [(3,2,12,6,20,4095),(4,3,20,10,25,667543),(5,4,32,12,51,2734261103)]:
            source=phase_source(e,f,p,q,b,c).replace('  always @(*) begin',helper+'  always @(*) begin')
            compact=compact_periodic_phase(source,exponent_bits=e,fraction_bits=f)
            shared=share_periodic_word_addition(compact);self.assertNotEqual(shared,compact)
            truth=OUT/f'phase_E{e}F{f}.truth'
            write_truth(truth,[phase_oracle(x,e,f,p,q,b,c) for x in range(1<<(1+e+f))],66)
            self.check(f'phase_shared_E{e}F{f}',truth,shared)
            for old,new in [('input signed [63:0] a,b','input [63:0] a,b'),
                            ('input signed [63:0] a,b','input signed [31:0] a,b'),('fp_add=a+b','fp_add=a-b')]:
                bad=compact.replace(old,new);self.assertEqual(share_periodic_word_addition(bad),bad)
        # Selector, odd sign and zero-sign identities do not depend on a
        # polynomial or floating-point format. Include extreme signed words.
        values=[-(1<<63),-8193,-1,0,1,8193,(1<<63)-1];mask=(1<<64)-1
        for s in values:
            for c in values:
                for quadrant in range(4):
                    for sign in range(2):
                        reference=[s,c,(-s)&mask,(-c)&mask][quadrant]&mask
                        if sign:reference=(-reference)&mask
                        chosen=(c if quadrant&1 else s)&mask
                        if quadrant&2:chosen=(-chosen)&mask
                        if sign:chosen=(-chosen)&mask
                        self.assertEqual(chosen,reference)
                        original_sign=sign if reference==0 else reference>>63
                        self.assertEqual(original_sign,sign if chosen==0 else chosen>>63)


    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()


if __name__=='__main__':unittest.main()

"""Complete staged-root contracts, an independent Decimal oracle and negatives."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import unittest
sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parent
P8 = SCRIPTS.parents[1]
REPO = SCRIPTS.parents[4]
sys.path.insert(0, str(SCRIPTS))
from truth.powered_root_compact_v8 import (emit_staged_cubic_root, root_format_properties,
                                          root_oracle, staged_significand)
from cost.RTL_cost_calculator import evaluate_rtl
ORIGINAL = REPO / 'paper_preparation/additional_experiments/matched_tt100_skill_followup_20261006_v6/generic/scripts'
sys.path.insert(0, str(ORIGINAL))
from verify.truth_yosys import verify
YOSYS = REPO / 'external/yosys/yosys'
os.environ['YOSYS'] = str(YOSYS)
os.environ['ABC'] = str(REPO / 'external/abc/abc')
os.environ['YOSYS_DATDIR'] = str(REPO / 'external/yosys/share')
SHA = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
OUT = P8 / 'powered_root_development/tests'
OUT.mkdir(parents=True, exist_ok=True)


def decimal_oracle(bits, e, f, precision):
    """Real cube root followed by TWO independently implemented RNE steps."""
    scale, maximum = 1 << f, (1 << e)-1
    sign = bits & (1 << (e+f)); mag = bits & ((1 << (e+f))-1)
    exp, frac = divmod(mag, scale)
    if exp == maximum:
        return maximum*scale+scale//2 if frac else sign+maximum*scale
    if exp == 0:
        return sign
    bias = (1 << (e-1))-1
    with localcontext() as context:
        context.prec = 110
        value = Decimal(scale+frac) * Decimal(2) ** (exp-bias-f)
        real = context.power(value, Decimal(1)/Decimal(3))
        # Cube roots are exactly on binade boundaries only for exact powers of
        # eight. Float exponent is used solely to seed exact Decimal adjustment.
        top = math.frexp(float(real))[1]-1
        while real < Decimal(2)**top: top -= 1
        while real >= Decimal(2)**(top+1): top += 1
        quantum = Decimal(2)**(top-precision)
        first = (real/quantum).to_integral_value(rounding=ROUND_HALF_EVEN)*quantum
        while first >= Decimal(2)**(top+1): top += 1
        second_quantum = Decimal(2)**(top-f)
        second = int((first/second_quantum).to_integral_value(rounding=ROUND_HALF_EVEN))
        return sign+(top+bias-1)*scale+second


def write_truth(path, words, width):
    mask = len(words)-1
    path.write_text('\n'.join(''.join(str((words[mask ^ x] >> bit)&1) for x in range(len(words)))
                              for bit in range(width))+'\n')


class PoweredRootTests(unittest.TestCase):
    records = []

    @classmethod
    def setUpClass(cls):
        assert SHA(YOSYS) == '440de91eddef71f0341eab0f7211978dc1b471fd6be09d4d8085da7250f6d487'
        assert SHA(SCRIPTS/'cost/RTL_cost_calculator.py') == '685d655fe1bb6dadeb36921cb3da42de2791cc31b252ea86aeb3e5a8bbd5b014'
        assert SHA(SCRIPTS/'cost/syntax_cost.csv') == '65a0ff43df653831655cba564349ac536c755b53335d97ee3860f410bccbebc0'
        assert SHA(Path(sys.modules['verify.truth_yosys'].__file__)) == '9af230bbb7f58926906890607d3b44a4b94a71f0d2780ea8d3d0ea4df7f58978'

    def check(self, label, truth, source, expected_pass=True):
        path = OUT/(label+'.v'); path.write_text(source)
        started = time.monotonic()
        result = verify(truth,path,YOSYS,use_cache=False,frontend_timeout=120,compile_timeout=120,run_timeout=180)
        cost, _, detail = evaluate_rtl(str(path))
        self.records.append({'label':label, 'candidate_sha256':SHA(path), 'truth_sha256':SHA(truth),
                             'cost':cost, 'detail':detail, 'wall_seconds':time.monotonic()-started,
                             'expected_pass':expected_pass, 'result':result})
        (OUT/(label+'.proof.json')).write_text(json.dumps(self.records[-1],indent=2)+'\n')
        if expected_pass:
            self.assertEqual(result['status'],'pass',(label,result))
        else:
            self.assertNotEqual(result['status'],'pass',(label,result))
            self.assertEqual(result['frontend'],'pass',(label,result))
            self.assertEqual(result['interface']['status'],'pass',(label,result))
            self.assertIn(result['status'],['mismatch','fail'],(label,result))
        return result

    def test_a_complete_independent_decimal_and_staged_properties(self):
        for e,f,p in [(3,2,23),(4,3,4),(5,4,6),(6,5,23)]:
            props=root_format_properties(e,f,p)
            self.assertTrue(props['staged_powered_midpoint_identity_verified'])
            for bits in range(1<<(1+e+f)):
                self.assertEqual(root_oracle(bits,e,f,p),decimal_oracle(bits,e,f,p),(e,f,p,bits))
            self.records.append({'label':f'Decimal_full_E{e}F{f}P{p}','vectors':1<<(1+e+f),
                                 'independent_oracle':'110-digit Decimal real cube root then explicit two RNE steps','status':'pass','properties':props})
        fp=root_format_properties(5,10,23)
        self.assertEqual(fp['direct_rounding_mismatches'],1)
        self.assertEqual(staged_significand(1361,1,10,10),1419)
        self.assertEqual(staged_significand(1361,1,10,23),1418)
        self.assertEqual(fp['effective_intermediate_precision'],19)
        self.assertEqual(root_format_properties(8,7,None)['effective_intermediate_precision'],7)
        for x in range(1<<16):
            self.assertEqual(root_oracle(x,8,7,None),root_oracle(x,8,7,23))

    def test_b_complete_nonbenchmark_rtl(self):
        for e,f,p in [(3,2,23),(4,3,4),(5,4,6),(6,5,23)]:
            width=1+e+f;truth=OUT/f'E{e}F{f}P{p}.truth'
            words=[decimal_oracle(x,e,f,p) for x in range(1<<width)]
            write_truth(truth,words,width)
            result=self.check(f'E{e}F{f}P{p}',truth,emit_staged_cubic_root(e,f,'Nonbenchmark staged cubic root',p))
            self.assertEqual(result['vectors'],1<<width)

    def test_c_actual_original_domains(self):
        # Each current source is freshly proved against the original input truth;
        # this does not read the fixed no-Skill RTL or import an answer.
        actual=REPO/'paper_preparation/additional_experiments/matched_tt100_skill_cost_20261007_v7/trials'
        for number,e,f,p in [(217,8,7,None),(237,5,10,23)]:
            truth=actual/f'ex{number}/with_skill/work/input.truth'
            result=self.check(f'actual_ex{number}',truth,emit_staged_cubic_root(e,f,'Exact staged cbrt',p))
            self.assertEqual(result['vectors'],65536)

    def test_d_negative_controls(self):
        e,f,p=4,3,4;width=1+e+f
        truth=OUT/'negative_reference.truth'
        write_truth(truth,[decimal_oracle(x,e,f,p) for x in range(1<<width)],width)
        source=emit_staged_cubic_root(e,f,'Negative-control staged cbrt',p)
        props=root_format_properties(e,f,p);work=3*(props['effective_intermediate_precision']+2)
        mutations=[
            ('signed_zero',source.replace(f'wire sign_in = x[{width-1}];','wire sign_in = 0;')),
            ('canonical_nan',source.replace(f"y = {width}'d{((1<<e)-1)*(1<<f)+(1<<(f-1))};",f"y = {width}'d0;")),
            ('daz',source.replace(f"if (same_exponent(exponent, {e}'d0)) code = 0;",f"if (same_exponent(exponent, {e}'d0)) code = {1<<f};")),
            ('double_round_interval',source.replace('alternating_bias = -2;','alternating_bias = 0;')),
            ('powered_threshold_direction',source.replace('begin greater = a > b; end','begin greater = a < b; end')),
        ]
        for name,changed in mutations:
            self.assertNotEqual(changed,source,name)
            self.check('negative_'+name,truth,changed,False)

    def test_e_bad_contracts_rejected(self):
        for args in [('5',10,23),(True,10,23),(5,0,23),(2,3,23),(9,3,23),(5,10,9),(5,10,33)]:
            with self.assertRaises(ValueError):emit_staged_cubic_root(args[0],args[1],precision=args[2])

    @classmethod
    def tearDownClass(cls):
        (OUT/'proof_summary.json').write_text(json.dumps({'schema':'staged-powered-root-controls/v1',
             'records':cls.records},indent=2)+'\n')


if __name__ == '__main__':
    unittest.main()

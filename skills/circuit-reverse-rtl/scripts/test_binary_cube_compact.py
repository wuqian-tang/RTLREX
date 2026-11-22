"""Independent float32/grid oracle, full RTL domains, and mutation controls."""
from bisect import bisect_left
import ctypes
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from truth.binary_cube_compact import cube_oracle, emit_binary_cube, format_properties

FROZEN = Path(__file__).resolve().parent
sys.path.insert(0, str(FROZEN))
from verify.truth_yosys import verify, default_yosys


class GridReference:
    """Host binary32 cube followed by an independent ordered target-value grid.

    Exact input significands have at most eleven bits: two host double
    multiplications retain all <=33 cube bits. ctypes then performs actual
    binary32 RNE, including its subnormal and infinity behavior.
    """
    def __init__(self, e, f):
        self.e, self.f, self.scale = e, f, 1 << f
        self.maximum, self.bias = (1 << e)-1, (1 << (e-1))-1
        self.infinity = self.maximum * self.scale
        self.grid = [self.decode(code) for code in range(self.infinity)]
        self.overflow_midpoint = self.grid[-1] + math.ldexp(1., self.bias-f-1)

    def decode(self, code):
        exp, frac = divmod(code, self.scale)
        if exp == 0:
            return math.ldexp(float(frac), 1-self.bias-self.f)
        return math.ldexp(float(self.scale+frac), exp-self.bias-self.f)

    def word(self, bits):
        code = bits & ((1 << (self.e+self.f))-1)
        sign = bits & (1 << (self.e+self.f))
        if code > self.infinity:
            return self.infinity + self.scale//2
        if code == self.infinity:
            return sign + self.infinity
        if code < self.scale:
            return sign
        value = self.grid[code]
        cubed = float(ctypes.c_float(value * value * value).value)
        if cubed >= self.overflow_midpoint:
            return sign + self.infinity
        upper = bisect_left(self.grid, cubed)
        if upper == 0:
            nearest = 0
        elif upper == len(self.grid):
            nearest = upper-1
        else:
            low_distance = cubed-self.grid[upper-1]
            high_distance = self.grid[upper]-cubed
            if low_distance == high_distance:
                nearest = upper if not upper & 1 else upper-1
            else:
                nearest = upper-1 if low_distance < high_distance else upper
        return sign + (nearest if nearest >= self.scale else 0)


def write_truth(path, words, output_width):
    mask = len(words)-1
    path.write_text('\n'.join(''.join(str((words[mask ^ x] >> bit) & 1)
                                     for x in range(len(words)))
                              for bit in range(output_width))+'\n')


def check(truth, candidate):
    return verify(truth, candidate, default_yosys(), use_cache=False,
                  frontend_timeout=120, compile_timeout=120, run_timeout=180,
                  replay_workers=4)


class BinaryCubeTests(unittest.TestCase):
    records = []


    def test_binary32_oracle_against_host_full_domain(self):
        # Normal exponents at both extremes include actual float32 underflow
        # and overflow for E8/F7, not just normalized mantissa-stage rounding.
        for e, f in [(8,7), (5,10), (3,2), (4,3), (5,4), (6,5)]:
            ref = GridReference(e,f)
            for x in range(1 << (1+e+f)):
                self.assertEqual(cube_oracle(x,e,f),ref.word(x),(e,f,x))
            self.records.append(dict(kind='independent_host_binary32_oracle',exponent_bits=e,fraction_bits=f,vectors=1 << (1+e+f),status='pass'))

    def test_complete_random_nonbenchmark_format_rtl(self):
        rng = random.Random(701103)
        admitted = []
        for e in range(3,7):
            for f in range(1,8):
                props = format_properties(e,f)
                if props['carry_free'] and props['binary32_stage_removable'] and (props['promotion_none'] or props['promotion_code_exact']):
                    admitted.append((e,f))
        chosen = rng.sample(admitted,4)
        self.assertEqual(len(chosen),4)
        for e,f in chosen:
            ref = GridReference(e,f)
            width = 1+e+f
            with tempfile.TemporaryDirectory() as directory:
                truth,candidate = Path(directory)/'input.truth',Path(directory)/'candidate.v'
                write_truth(truth,[ref.word(x) for x in range(1 << width)],width)
                candidate.write_text(emit_binary_cube(e,f,'Seeded nonbenchmark format control'))
                result = check(truth,candidate)
                self.assertEqual(result['status'],'pass',(e,f,result))
                self.assertEqual(result['vectors'],1 << width)
                self.records.append(dict(kind='nonbenchmark_complete_RTL',exponent_bits=e,fraction_bits=f,result=result))

    def test_invalid_and_unproved_simplifications_rejected(self):
        for e,f in [('8',7),(8,'7'),(True,7),(2,7),(9,7),(8,0),(8,11)]:
            with self.assertRaises(ValueError):
                emit_binary_cube(e,f)
        # These genuine formats contain carry; the emitter must reject rather
        # than silently applying the carry-free concatenation theorem.
        for e,f in [(3,2),(4,3),(6,9)]:
            self.assertFalse(format_properties(e,f)['carry_free'])
            with self.assertRaises(ValueError):
                emit_binary_cube(e,f)

    def test_rounding_ftz_sign_and_nan_mutations_detected(self):
        mutations = [
            (8,7,lambda s:s.replace('wire sign_in = x[15];','wire sign_in = 0;'),'signed zero'),
            (8,7,lambda s:s.replace('if (input_magnitude > 32640)','if (input_magnitude >= 32640)'),'infinity versus NaN'),
            (8,7,lambda s:s.replace("16'd32704","16'd32641"),'canonical NaN'),
            (5,10,lambda s:s.replace(' - 1 + product[rounding_shift]',''),'nearest even'),
            (5,10,lambda s:s.replace("code == 1023 ? 15'd1024 : 0",'0'),'FTZ promotion'),
        ]
        for e,f,mutation,label in mutations:
            ref=GridReference(e,f);width=1+e+f
            with tempfile.TemporaryDirectory() as directory:
                truth,candidate=Path(directory)/'input.truth',Path(directory)/'candidate.v'
                source=emit_binary_cube(e,f,'negative '+label)
                changed=mutation(source)
                self.assertNotEqual(changed,source,label)
                write_truth(truth,[ref.word(x) for x in range(1 << width)],width)
                candidate.write_text(changed)
                result=check(truth,candidate)
                self.assertNotEqual(result['status'],'pass',(label,result))
                self.assertEqual(result.get('frontend'),'pass',(label,result))
                self.assertEqual(result.get('interface',{}).get('status'),'pass',(label,result))
                self.records.append(dict(kind='mutation_detected',label=label,exponent_bits=e,fraction_bits=f,result=result))


if __name__ == '__main__':
    unittest.main()

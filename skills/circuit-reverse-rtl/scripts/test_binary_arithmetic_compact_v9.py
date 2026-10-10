#!/usr/bin/env python3
"""Independent exact integer reference for compact finite binary arithmetic."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from fractions import Fraction
from functools import lru_cache
from bisect import bisect_left

sys.path.insert(0,str(Path(__file__).resolve().parent))
from truth.binary_arithmetic_compact_v9 import (emit_finite_hypot,emit_binary_square,
                                               emit_binary_reciprocal_power,
                                               _reciprocal_ftz_boundary_safe,
                                               emit_binary_reciprocal_sqrt,
                                               emit_finite_add)
from verify.truth_yosys import verify

from verify.truth_yosys import default_yosys
YOSYS = default_yosys()


def decoded(code,e,f):
    exponent,fraction=divmod(code,1 << f)
    return fraction if exponent==0 else ((1 << f)+fraction) << (exponent-1)


def hypot_reference(packed,e,f):
    payload=e+f; width=payload+1; maximum=(1 << payload)-1
    a,b=(packed >> width)&maximum,packed&maximum
    if maximum in (a,b):
        return maximum
    target=4*(decoded(a,e,f)**2+decoded(b,e,f)**2)
    # Independent global quantizer, not the emitted max-start recurrence.
    for code in range(maximum-1):
        midpoint=decoded(code,e,f)+decoded(code+1,e,f)
        threshold=midpoint*midpoint
        if target<threshold or (target==threshold and code%2==0):
            return code
    return maximum-1


def binary_value(code,e,f):
    exponent,fraction=divmod(code,1 << f);bias=(1 << (e-1))-1
    significand=fraction if exponent==0 else (1 << f)+fraction
    power=(1 if exponent==0 else exponent)-bias-f
    return Fraction(significand)*(Fraction(2)**power)


@lru_cache(None)
def finite_values(e,f):
    return [binary_value(code,e,f) for code in range(((1 << e)-1) << f)]


def square_reference(x,e,f):
    magnitude=x&((1 << (e+f))-1);exponent,fraction=divmod(magnitude,1 << f)
    maximum=(1 << e)-1;infinity=maximum << f
    if exponent==maximum:return infinity|(1 << (f-1)) if fraction else infinity
    if exponent==0:return 0
    value=binary_value(magnitude,e,f)**2
    largest=binary_value(infinity-1,e,f)
    overflow=largest+(largest-binary_value(infinity-2,e,f))/2
    if value>=overflow:return infinity
    values=finite_values(e,f);position=bisect_left(values,value)
    nearest=min({max(0,position-1),min(infinity-1,position)},
                key=lambda code:(abs(value-values[code]),code%2))
    return nearest if nearest>>f else 0


def reciprocal_power_reference(x,e,f,p):
    magnitude=x&((1 << (e+f))-1);exponent,fraction=divmod(magnitude,1 << f)
    maximum=(1 << e)-1;infinity=maximum << f;sign=(x >> (e+f)) if p%2 else 0
    if exponent==maximum:
        return infinity|(1 << (f-1)) if fraction else sign << (e+f)
    if exponent==0:return (sign << (e+f))|infinity
    value=Fraction(1,binary_value(magnitude,e,f)**p)
    largest=binary_value(infinity-1,e,f)
    overflow=largest+(largest-binary_value(infinity-2,e,f))/2
    if value>=overflow:return (sign << (e+f))|infinity
    values=finite_values(e,f);position=bisect_left(values,value)
    nearest=min({max(0,position-1),min(infinity-1,position)},
                key=lambda code:(abs(value-values[code]),code%2))
    return (sign << (e+f))|(nearest if nearest>>f else 0)


def reciprocal_sqrt_reference(x,e,f):
    magnitude=x&((1 << (e+f))-1);exponent,fraction=divmod(magnitude,1 << f)
    infinity=((1 << e)-1) << f;sign=x >> (e+f)
    if exponent==0:return (sign << (e+f))|infinity
    if sign or magnitude>infinity:return infinity|(1 << (f-1))
    if magnitude==infinity:return 0
    value=Fraction(1,binary_value(magnitude,e,f));values=finite_values(e,f)
    for code in range(infinity-1):
        threshold=((values[code]+values[code+1])/2)**2
        if value<threshold or (value==threshold and code%2==0):return code if code>>f else 0
    return infinity-1


@lru_cache(None)
def finite_decoded_values(e,f):
    return [decoded(code,e,f) for code in range((1 << (e+f))-1)]


def finite_add_reference(x,e,f):
    payload=e+f;width=payload+1;maximum=(1 << payload)-1
    a,b=(x >> width)&maximum,x&maximum;sa=x >> (2*width-1);sb=(x >> payload)&1
    if maximum in (a,b):return maximum
    value=decoded(a,e,f)*(-1 if sa else 1)+decoded(b,e,f)*(-1 if sb else 1)
    sign=(value<0) or (value==0 and sa and sb);absolute=abs(value)
    values=finite_decoded_values(e,f);position=bisect_left(values,absolute)
    nearest=min({max(0,position-1),min(maximum-1,position)},
                key=lambda code:(abs(absolute-values[code]),code%2))
    return (int(sign) << payload)|nearest


class BinaryArithmeticTests(unittest.TestCase):
    def prove(self,n,m,words,source):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);truth=p/'input.truth';rtl=p/'final.v';mask=(1 << n)-1
            truth.write_text('\n'.join(''.join(str((words[x^mask] >> bit)&1)
                                                for x in range(1 << n))
                                      for bit in range(m))+'\n');rtl.write_text(source)
            result=verify(truth,rtl,YOSYS,use_cache=False,
                          frontend_timeout=120,compile_timeout=120,run_timeout=180)
            self.assertEqual(result['frontend'],'pass',result)
            self.assertEqual(result['status'],'pass',result)
            self.assertEqual(result['vectors'],1 << n)

    def reject(self,n,m,words,source):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);truth=p/'input.truth';rtl=p/'mutant.v';mask=(1 << n)-1
            truth.write_text('\n'.join(''.join(str((words[x^mask] >> bit)&1)
                                                for x in range(1 << n))
                                      for bit in range(m))+'\n');rtl.write_text(source)
            result=verify(truth,rtl,YOSYS,use_cache=False,
                          frontend_timeout=120,compile_timeout=120,run_timeout=180)
            self.assertEqual(result['frontend'],'pass',result)
            self.assertEqual(result['status'],'mismatch',result)

    def test_complete_nonbenchmark_formats(self):
        for e,f in ((2,1),(3,1),(3,2),(2,3)):
            width=e+f+1; n=2*width
            words=[hypot_reference(x,e,f) for x in range(1 << n)]
            with tempfile.TemporaryDirectory() as directory:
                p=Path(directory);truth=p/'input.truth';source=p/'final.v'
                mask=(1 << n)-1
                truth.write_text('\n'.join(''.join(str((words[x^mask] >> bit)&1)
                                                    for x in range(1 << n))
                                          for bit in range(width))+'\n')
                source.write_text(emit_finite_hypot(e,f))
                result=verify(truth,source,YOSYS,use_cache=False,
                              frontend_timeout=120,compile_timeout=120,run_timeout=180)
                self.assertEqual(result['frontend'],'pass',result)
                self.assertEqual(result['status'],'pass',result)
                self.assertEqual(result['vectors'],1 << n)

    def test_square_complete_nonbenchmark_formats(self):
        for e,f in ((3,1),(3,2),(3,4),(4,2),(3,7)):
            width=e+f+1
            words=[square_reference(x,e,f) for x in range(1 << width)]
            self.prove(width,width,words,emit_binary_square(e,f))

    def test_square_narrowed_round_bias_is_rejected(self):
        e,f=3,7;width=e+f+1
        words=[square_reference(x,e,f) for x in range(1 << width)]
        source=emit_binary_square(e,f).replace("aligned + 17'd127","aligned + 16'd127")
        self.assertEqual(words[(2 << f)+53],2 << f)
        self.reject(width,width,words,source)

    def test_square_parameter_negative_controls(self):
        for e,f in ((2,2),(9,2),(5,0),(5,24),(False,2),(5,True),(5.0,2),(5,2.0)):
            with self.assertRaises(ValueError):emit_binary_square(e,f)

    def test_reciprocal_power_complete_nonbenchmark_formats(self):
        for p in (2,3):
            for e,f in ((3,1),(3,2),(4,2),(3,4)):
                width=e+f+1
                words=[reciprocal_power_reference(x,e,f,p) for x in range(1 << width)]
                self.prove(width,width,words,emit_binary_reciprocal_power(e,f,p))

    def test_reciprocal_staged_ftz_format_guard(self):
        with self.assertRaisesRegex(ValueError,'staged FTZ'):
            emit_binary_reciprocal_power(3,5,3)
        for e,f,p in ((3,5,3),(3,7,3),(4,5,2),(4,5,3),(3,2,3)):
            scale=1 << f;bias=(1 << (e-1))-1
            exhaustive=True
            for exponent in range(1,(1 << e)-1):
                base=(p+1)*bias-p*exponent
                if not 1 <= base <= p+1:continue
                threshold=1 << ((p+1)*(bias+f)-p*exponent)
                for s in range(scale,2*scale):
                    d=s**p;n=1+sum(d>(1 << (p*f+j)) for j in range(1,p))
                    q=((1 << ((p+1)*f+n))+d//2)//d
                    exhaustive &= ((base-1-n)*scale+q >= scale)==(d*(2*scale-1)<=threshold)
            self.assertEqual(_reciprocal_ftz_boundary_safe(e,f,p),exhaustive)

    def test_reciprocal_power_signed_bound_mutation_is_rejected(self):
        e,f,p=3,2,3;width=e+f+1
        words=[reciprocal_power_reference(x,e,f,p) for x in range(1 << width)]
        source=emit_binary_reciprocal_power(e,f,p).replace('input signed [','input [')
        self.reject(width,width,words,source)

    def test_reciprocal_power_hidden_bit_mutation_is_rejected(self):
        e,f,p=3,2,2;width=e+f+1
        words=[reciprocal_power_reference(x,e,f,p) for x in range(1 << width)]
        source=emit_binary_reciprocal_power(e,f,p).replace("9'sd8 - exponent", "9'sd9 - exponent")
        self.reject(width,width,words,source)

    def test_reciprocal_power_parameter_negative_controls(self):
        for args in ((2,2,2),(3,0,2),(3,24,2),(3,2,1),(3,2,4),(True,2,2),(3,2,True)):
            with self.assertRaises(ValueError):emit_binary_reciprocal_power(*args)

    def test_reciprocal_sqrt_complete_nonbenchmark_formats(self):
        for e,f in ((3,1),(3,2),(3,4),(4,2)):
            width=e+f+1;words=[reciprocal_sqrt_reference(x,e,f) for x in range(1 << width)]
            self.prove(width,width,words,emit_binary_reciprocal_sqrt(e,f))

    def test_reciprocal_sqrt_nan_guard_mutation_is_rejected(self):
        e,f=3,2;width=e+f+1;words=[reciprocal_sqrt_reference(x,e,f) for x in range(1 << width)]
        source=emit_binary_reciprocal_sqrt(e,f).replace("6'd28) ? 6'd30", "6'd63) ? 6'd30")
        self.reject(width,width,words,source)

    def test_reciprocal_sqrt_rounding_bias_mutation_is_rejected(self):
        e,f=3,4;width=e+f+1;words=[reciprocal_sqrt_reference(x,e,f) for x in range(1 << width)]
        source=emit_binary_reciprocal_sqrt(e,f).replace('root + biased_radicand / root + 1','root + biased_radicand / root')
        self.reject(width,width,words,source)

    def test_reciprocal_sqrt_format_type_negative_controls(self):
        for e,f in ((2,2),(9,2),(3,0),(3,24),(False,2),(3,True),(3.0,2),(3,2.0)):
            with self.assertRaises(ValueError):emit_binary_reciprocal_sqrt(e,f)

    def test_finite_add_complete_nonbenchmark_formats(self):
        for e,f in ((2,1),(3,1),(3,2),(2,3),(5,2)):
            width=e+f+1;n=2*width;words=[finite_add_reference(x,e,f) for x in range(1 << n)]
            self.prove(n,width,words,emit_finite_add(e,f))

    def test_finite_add_negative_zero_mutation_is_rejected(self):
        e,f=3,2;width=e+f+1;n=2*width
        words=[finite_add_reference(x,e,f) for x in range(1 << n)]
        source=emit_finite_add(e,f).replace('(negative || (sa && sb))','negative')
        self.assertEqual(words[((1 << (width-1)) << width)|(1 << (width-1))],1 << (width-1))
        self.reject(n,width,words,source)

    def test_finite_add_even_tie_mutation_is_rejected(self):
        e,f=3,2;width=e+f+1;n=2*width
        words=[finite_add_reference(x,e,f) for x in range(1 << n)]
        source=emit_finite_add(e,f).replace('(shift && !value[shift])',"1'b0")
        self.reject(n,width,words,source)

    def test_finite_add_format_type_negative_controls(self):
        for e,f in ((1,2),(6,2),(3,0),(3,4),(True,2),(3,False),(3.0,2),(3,2.0)):
            with self.assertRaises(ValueError):emit_finite_add(e,f)

    def test_format_and_contract_negative_controls(self):
        for e,f in ((1,2),(6,2),(4,0),(3,4),(True,2),(4,False),(4.0,3),(4,3.0)):
            with self.assertRaises(ValueError):emit_finite_hypot(e,f)

    def test_adjacent_boundary_and_odd_tie_fact(self):
        for e,f in ((2,1),(3,1),(3,2),(2,3),(4,3),(5,2)):
            maximum=(1 << (e+f))-1
            values={decoded(code,e,f) for code in range(maximum)}
            squares={value*value for value in values}
            for code in range(maximum-1):
                midpoint=decoded(code,e,f)+decoded(code+1,e,f)
                if code%2==1 and midpoint%2==0:
                    target=midpoint*midpoint//4
                    self.assertFalse(any(target-square in squares for square in squares),
                                     (e,f,code))

    def test_wrong_inclusive_midpoint_is_rejected(self):
        e,f=2,2;width=e+f+1;n=2*width
        words=[hypot_reference(x,e,f) for x in range(1 << n)]
        # 5^2+12^2=13^2: the even lower output code10 encodes12.
        packed=(10 << width)|5
        self.assertEqual(words[packed],10)
        source=emit_finite_hypot(e,f)
        bits=2*(((1 << e)-2)+f+1)+3
        helper=f'''  function at_least;
    input [{bits-1}:0] left, right;
    begin at_least = left >= right; end
  endfunction
'''
        source=source.replace('  always @(*) begin',helper+'  always @(*) begin')
        source=source.replace('greater(four_value, midpoint_squared(code, 1\'b1))',
                              'at_least(four_value, midpoint_squared(code, 1\'b1))')
        self.reject(n,width,words,source)

    def test_nan_and_saturation_clamp_mutation_is_rejected(self):
        e,f=2,2;width=e+f+1;n=2*width
        words=[hypot_reference(x,e,f) for x in range(1 << n)]
        source=emit_finite_hypot(e,f).replace("greater(4'd14, code) &&",'')
        self.assertEqual(words[(15 << width)|15],15)
        self.reject(n,width,words,source)


if __name__=='__main__':unittest.main()

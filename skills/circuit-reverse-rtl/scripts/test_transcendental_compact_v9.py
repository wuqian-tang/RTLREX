"""Independent nonbenchmark word-kernel oracle and mutation controls."""
from pathlib import Path
import tempfile
import re
import subprocess
import unittest

from truth.transcendental_compact_v9 import compact_transcendental_word_semantics
from verify.truth_yosys import verify, default_yosys

HELPERS = '''
  function signed [64:0] semantic_add65;
    input signed [64:0] a, b;
    begin semantic_add65 = a + b; end
  endfunction
  function signed [63:0] semantic_rne64;
    input signed [63:0] value;
    input [5:0] shift;
    input signed [64:0] bias;
    reg signed [64:0] extended;
    begin
      extended = value;
      extended = semantic_add65(extended, bias);
      extended = semantic_add65(extended, value[shift]);
      semantic_rne64 = extended >>> shift;
    end
  endfunction
  function signed [63:0] fp_add;
    input signed [63:0] a, b;
    begin fp_add = semantic_add65(a, b); end
  endfunction
  function signed [63:0] fp_sub;
    input signed [63:0] a, b;
    begin fp_sub = fp_add(a, -b); end
  endfunction
  function signed [63:0] fp_asl;
    input signed [63:0] a, b;
    begin fp_asl = a <<< b; end
  endfunction
  function signed [63:0] fp_asr;
    input signed [63:0] a, b;
    begin fp_asr = a >>> b; end
  endfunction
  function signed [63:0] fp_div;
    input signed [63:0] a, b;
    begin fp_div = a / b; end
  endfunction
  function signed [63:0] fp_mul;
    input signed [63:0] a, b;
    begin fp_mul = a * b; end
  endfunction
  function fp_ge;
    input signed [63:0] a, b;
    begin fp_ge = a >= b; end
  endfunction
  function fp_eq;
    input signed [63:0] a, b;
    begin fp_eq = a == b; end
  endfunction
  function fp_ne;
    input signed [63:0] a, b;
    begin fp_ne = a != b; end
  endfunction
  function signed [63:0] fp_mux;
    input signed [63:0] condition;
    input signed [63:0] a, b;
    begin fp_mux = condition ? a : b; end
  endfunction
'''


def toy(e, f):
    width = 1 + e + f
    return f'''module top(input [{width-1}:0] x, output reg [15:0] y);
  wire input_sign = x[{width-1}];
  wire [{e-1}:0] input_exponent = x[{width-2}:{f}];
  wire [{f-1}:0] input_fraction = x;
  localparam signed [63:0] ONE = 64'sd8;
  localparam signed [63:0] HALF = 64'sd4;
  reg signed [63:0] xq, k, eq, normq, bin_exp, rounded, rounded32, out_exp;
{HELPERS}
  always @(*) begin
    xq = 0; k = 0; eq = 0; normq = 0; bin_exp = 0;
    rounded = 0; rounded32 = 0; out_exp = 0; y = 0;
    if (fp_eq(input_exponent, {e}'h{(1<<e)-1:x})) begin
      if (fp_ne(input_fraction, 0)) y = 16'h7fc0;
      else if (input_sign) y = 16'h0000;
      else y = 16'h7f00;
    end else if (fp_eq(input_exponent, 0)) begin
      y = 16'h3f80;
    end else begin
      xq = fp_asl(fp_add(8, input_fraction), input_exponent);
      if (input_sign)
        xq = (-xq);
      if (fp_ge(xq, 0))
        k = fp_div((fp_add(xq, HALF)), ONE);
      else
        k = fp_div((fp_sub(xq, HALF)), ONE);
      eq = fp_add(2, input_fraction);
      if (fp_ge(eq, ONE)) begin
        normq = eq;
        bin_exp = k;
      end else begin
        normq = fp_asl(eq, 1);
        bin_exp = fp_sub(k, 1);
      end
      rounded32 = semantic_rne64(xq, 3, 65'sd3);
      rounded = semantic_rne64(normq, 2, 65'sd1);
      out_exp = fp_add(fp_mul(bin_exp, 16), fp_add(rounded, rounded32));
      y = out_exp;
    end
  end
endmodule
'''


def reference(value, e, f):
    sign = value >> (e+f)
    exponent = (value >> f) % (1 << e)
    fraction = value % (1 << f)
    if exponent == (1 << e)-1:
        return 0x7fc0 if fraction else (0 if sign else 0x7f00)
    if exponent == 0:
        return 0x3f80
    xq = (8+fraction) * (1 << exponent) * (-1 if sign else 1)
    nearest = xq + (4 if xq >= 0 else -4)
    k = (abs(nearest)//8) * (-1 if nearest < 0 else 1)
    eq = 2+fraction
    normq, bin_exp = (eq,k) if eq >= 8 else (2*eq,k-1)
    def rne(number, shift):
        return (number + (1 << (shift-1))-1 + ((number >> shift)&1)) >> shift
    return (bin_exp*16+rne(normq,2)+rne(xq,3)) & 65535


def check(source,e,f):
    width = 1+e+f
    values = [reference(x,e,f)for x in range(1<<width)]
    mask = len(values)-1
    with tempfile.TemporaryDirectory()as temporary:
        d=Path(temporary);t=d/'input.truth';v=d/'candidate.v'
        t.write_text('\n'.join(''.join(str((values[x^mask]>>b)&1)for x in range(len(values)))for b in range(16))+'\n')
        v.write_text(source)
        return verify(t,v,default_yosys(),use_cache=False,frontend_timeout=120,compile_timeout=120,run_timeout=180)


class TranscendentalWordTests(unittest.TestCase):
    def test_nonbenchmark_complete_mathematical_domains(self):
        for e,f in ((2,2),(2,3),(3,4)):
            with self.subTest(format=(e,f)):
                original=toy(e,f);changed=compact_transcendental_word_semantics(original)
                self.assertNotEqual(original,changed)
                for source in (original,changed):
                    result=check(source,e,f)
                    self.assertEqual(result['frontend'],'pass',result)
                    self.assertEqual(result['status'],'pass',result)

    def test_round_parity_and_signed_quotient_negative_controls(self):
        source=compact_transcendental_word_semantics(toy(3,4))
        mutants=[source.replace('semantic_quotient_parity = semantic_asr65(value, shift);','semantic_quotient_parity = 0;'),
                 source.replace("fp_mux(fp_ge(k, 0), 0, 64'sd7)","fp_mux(fp_ge(k, 0), 0, 64'sd0)")]
        for mutant in mutants:
            self.assertNotEqual(source,mutant)
            result=check(mutant,3,4)
            self.assertEqual(result['frontend'],'pass',result)
            self.assertEqual(result['status'],'mismatch',result)

    def test_signed64_round_and_modular_quotient_boundaries(self):
        minimum, maximum = -(1<<63), (1<<63)-1
        values = {minimum, minimum+1, minimum+3, minimum+4, minimum+7,
                  maximum, maximum-1, maximum-3, maximum-4, maximum-7,
                  -9, -8, -7, -4, -1, 0, 1, 4, 7, 8, 9}
        for power in (7,15,31,62):
            for delta in (-1,0,1):
                values.update(((1<<power)+delta, -(1<<power)+delta))
        mask = (1<<64)-1
        def signed(number):
            return (number+(1<<63))%(1<<64)-(1<<63)
        for transformed in (False,True):
            source = toy(3,4)
            if transformed:
                source = compact_transcendental_word_semantics(source)
            helpers = '\n'.join(m[0] for m in re.finditer(r'  function\b.*?  endfunction',source,re.S))
            quotient = ('semantic_asr65(fp_add(biased, fp_mux(fp_ge(biased, 0), 0, 64\'sd7)), 3)'
                        if transformed else "biased / 64'sd8")
            candidate = ("module top(input [63:0] x, input [5:0] shift, input signed [64:0] bias, "
                         "output [63:0] rne, asr, quotient);\n" + helpers +
                         "\nwire signed [63:0] biased = fp_add(x, fp_mux(fp_ge(x, 0), 64'sd4, fp_sub(0, 64'sd4)));\n"
                         "assign rne = semantic_rne64(x, shift, bias);\nassign asr = fp_asr(x, shift);\n"
                         "assign quotient = " + quotient + ";\nendmodule\n")
            statements=[]
            for number in sorted(values):
                biased=signed(number+(4 if number>=0 else -4))
                trunc=(abs(biased)//8)*(-1 if biased<0 else 1)
                for shift in (1,2,7,15,31,62,63):
                    bias=(1<<(shift-1))-1
                    rounded=(number+bias+((number>>shift)&1))>>shift
                    statements.append(f"x=64'h{number&mask:016x}; shift=6'd{shift}; bias=65'd{bias}; #1; "
                        f"if(rne!==64'h{rounded&mask:016x} || asr!==64'h{(number>>shift)&mask:016x} || "
                        f"quotient!==64'h{trunc&mask:016x}) begin $display(\"FAIL\"); $finish(0); end")
            testbench=('module tb; reg [63:0] x; reg [5:0] shift; reg signed [64:0] bias; '
                       'wire [63:0] rne, asr, quotient; top dut(x,shift,bias,rne,asr,quotient); '
                       'initial begin\n'+'\n'.join(statements)+'\n$display("PASS"); $finish(0); end endmodule\n')
            with tempfile.TemporaryDirectory()as temporary:
                d=Path(temporary);v=d/'candidate.v';lowered=d/'lowered.v';tb=d/'tb.v';sim=d/'simv'
                v.write_text(candidate);tb.write_text(testbench)
                flow=f'read_verilog {v}; hierarchy -check -top top; proc; opt; check -assert; write_verilog -noattr {lowered}'
                front=subprocess.run([default_yosys(),'-Q','-T','-p',flow],capture_output=True,text=True,timeout=120)
                self.assertEqual(front.returncode,0,front.stderr)
                compile=subprocess.run(['iverilog','-g2012','-s','tb','-o',str(sim),str(lowered),str(tb)],capture_output=True,text=True,timeout=120)
                self.assertEqual(compile.returncode,0,compile.stderr)
                replay=subprocess.run(['vvp',str(sim)],capture_output=True,text=True,timeout=180)
                self.assertEqual(replay.returncode,0,replay.stderr)
                self.assertEqual(replay.stdout.strip(),'PASS',replay.stdout)

    def test_unsupported_scopes_and_helper_widths_fail_closed(self):
        source=toy(3,4)
        unsupported=[source.replace('input [7:0] x','input signed [7:0] x'),
                     source.replace('function signed [63:0] fp_add','function signed [31:0] fp_add'),
                     source.replace('extended >>> shift','extended >> shift'),
                     source+'\n`define UNSUPPORTED 1\n']
        for candidate in unsupported:
            self.assertEqual(compact_transcendental_word_semantics(candidate),candidate)


if __name__=='__main__':
    unittest.main()

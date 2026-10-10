"""Independent rational-oracle controls for the packed lane sum."""
from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from truth.packed_sum_compact import emit_packed_q11_sum
from verify.truth_yosys import default_yosys, verify


def oracle(total):
    value = Fraction(total, 2)
    def decode(code):
        exponent, fraction = divmod(code, 8)
        return Fraction(fraction if exponent == 0 else 8 + fraction) * Fraction(2) ** (max(exponent, 1) - 10)
    return min(range(127), key=lambda code: (abs(decode(code)-value), code % 2))


class PackedSumTests(unittest.TestCase):
    def test_full_nonbenchmark_lane_domains(self):
        for lanes in (1, 3, 5):
            width = 2 * lanes
            words = [oracle(sum((value >> (2 * index)) % 4 for index in range(lanes)))
                     for value in range(1 << width)]
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                truth, source = directory / 'input.truth', directory / 'candidate.v'
                mask = (1 << width) - 1
                truth.write_text('\n'.join(''.join(str((words[value ^ mask] >> bit) & 1)
                                                  for value in range(1 << width))
                                          for bit in range(8)) + '\n')
                source.write_text(emit_packed_q11_sum(lanes, 'independent lane-domain control'))
                result = verify(truth, source, default_yosys(), use_cache=False)
                self.assertEqual(result['frontend'], 'pass', result)
                self.assertEqual(result['status'], 'pass', result)
                self.assertEqual(result['vectors'], 1 << width)

    def test_all_supported_aggregate_values(self):
        # Ten lanes admit every integer total from 0 to 30. Exercise the
        # actual reduction, including its maximum and every RNE parity.
        lanes = 10
        words = []
        for total in range(31):
            remaining = total
            value = 0
            for index in range(lanes):
                lane = min(remaining, 3)
                value += lane << (2 * index)
                remaining -= lane
            words.append((value, oracle(total)))
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, bench, executable = directory / 'candidate.v', directory / 'tb.v', directory / 'simv'
            source.write_text(emit_packed_q11_sum(lanes, 'maximum-lane boundary control'))
            body = '\n'.join(f'x=20\'d{value}; #1; if(y !== 8\'d{expected}) $fatal(1,"total {i}");'
                             for i, (value, expected) in enumerate(words))
            bench.write_text('module tb; reg [19:0] x; wire [7:0] y; top dut(x,y); initial begin\n' + body + '\n$finish; end endmodule\n')
            compile_result = subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable), str(source), str(bench)], capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(['vvp', str(executable)], capture_output=True, text=True)
            self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)

    def test_contract_bounds(self):
        for lanes in (0, 11, 1.5, True):
            with self.assertRaises(ValueError):
                emit_packed_q11_sum(lanes, 'invalid')


if __name__ == '__main__':
    unittest.main()

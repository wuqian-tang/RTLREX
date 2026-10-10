#!/usr/bin/env python3
"""Bounded formal regression for widths, truncation and all signedness modes."""
import argparse
import os
import shutil
import json
import subprocess
from pathlib import Path
from arithmetic_lowering import lower, binary

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--yosys', default=os.environ.get('YOSYS', 'yosys'))
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
yosys = shutil.which(args.yosys)
if not yosys:
    parser.error('Yosys executable not found')
CHECK = args.output.resolve()
CHECK.mkdir(parents=True, exist_ok=True)
module = {'attributes': {}, 'ports': {'a': {'direction': 'input', 'bits': list(range(2, 8))}}, 'cells': {}, 'netnames': {}}
next_bit = 8


def mul(a, b, width, sa=0, sb=0):
    global next_bit
    # Yosys normalizes mixed-sign arithmetic to two unsigned cell operands.
    sa = sb = int(bool(sa and sb))
    y = list(range(next_bit, next_bit+width))
    next_bit += width
    name = f'product{len(module["cells"])}'
    module['ports']['out_'+name] = {'direction': 'output', 'bits': y}
    module['cells'][name] = {
        'hide_name': 0, 'type': '$mul', 'attributes': {},
        'parameters': {'A_SIGNED': binary(sa), 'B_SIGNED': binary(sb),
                       'A_WIDTH': binary(len(a)), 'B_WIDTH': binary(len(b)), 'Y_WIDTH': binary(width)},
        'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'},
        'connections': {'A': a, 'B': b, 'Y': y},
    }


for n in range(1, 7):
    for width in sorted({1, n, 2*n, 2*n+3}):
        mul(list(range(2, 2+n)), list(range(2, 2+n)), width)
for aw in (1, 3, 6):
    for bw in (2, 4):
        for coefficient in sorted({0, 1, 3, (1<<bw)-1, 1<<(bw-1)}):
            bits = list(reversed(format(coefficient, f'0{bw}b')))
            for width in (1, 3, 6, 9):
                for sa in (0, 1):
                    for sb in (0, 1):
                        mul(list(range(2, 2+aw)), bits, width, sa, sb)
                        mul(bits, list(range(2, 2+aw)), width, sb, sa)
net = {'creator': 'Generic arithmetic rule regression', 'modules': {'top': module}}
rewritten, events = lower(net)
(CHECK/'before.json').write_text(json.dumps(net)+'\n')
(CHECK/'after.json').write_text(json.dumps(rewritten)+'\n')
script = f'''read_json "{CHECK / 'before.json'}"
rename top gold
read_json "{CHECK / 'after.json'}"
rename top gate
miter -equiv -make_assert -flatten gold gate miter
hierarchy -top miter
opt
sat -verify -prove-asserts -show-inputs -show-outputs
'''
(CHECK/'check.ys').write_text(script)
with (CHECK/'check.log').open('w') as log:
    result = subprocess.run([yosys, '-Q', '-T', '-s', CHECK/'check.ys'], stdout=log, stderr=subprocess.STDOUT, timeout=120)
assert result.returncode == 0, 'Formal rule regression failed. See check.log.'
assert 'SUCCESS!' in (CHECK/'check.log').read_text()
(CHECK/'result.json').write_text(json.dumps({'status': 'pass', 'method': 'Yosys SAT miter, all assertions proved', 'multiplier_cells_checked': len(module['cells']), 'rewrites_checked': len(events), 'scope': 'Unsigned square sizes 1..6, truncated/exact/widened outputs. Constant coefficients in both port positions, multiple operand/constant/output widths, all four signedness combinations, all input assignments.'}, indent=2)+'\n')
print(f'PASS: {len(events)} generic rewrites, all assertions proved')

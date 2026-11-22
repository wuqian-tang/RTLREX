#!/usr/bin/env python3
"""Check bounded unsigned-cube normalization and preserve signed negative exponents."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

from arithmetic_lowering import binary
from prepare_inputs import normalize_cubes
from run_experiment import quote


def fixture(n, width, exponent, signed):
    bits = list(range(2, n + 2))
    out = list(range(n + 2, n + 2 + width))
    cell = {'hide_name': 1, 'type': '$pow', 'attributes': {},
            'parameters': {'A_SIGNED': binary(0), 'B_SIGNED': binary(signed),
                           'A_WIDTH': binary(n), 'B_WIDTH': binary(len(exponent)), 'Y_WIDTH': binary(width)},
            'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'},
            'connections': {'A': bits, 'B': exponent, 'Y': out}}
    return {'creator': 'Cube-rule regression', 'modules': {'top': {
        'attributes': {}, 'ports': {'x': {'direction': 'input', 'bits': bits},
                                   'y': {'direction': 'output', 'bits': out}},
        'cells': {'power': cell}, 'netnames': {}}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yosys', default=os.environ.get('YOSYS', 'yosys'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    executable = shutil.which(args.yosys)
    if not executable:
        parser.error('Yosys executable not found')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    count = 0
    skipped = 0
    for n in range(1, 7):
        for width in sorted({1, n, 3 * n, 3 * n + 2}):
            # The same bit string '11' denotes unsigned +3 or signed -1.
            negative = fixture(n, width, ['1', '1'], 1)
            unchanged, events = normalize_cubes(copy.deepcopy(negative))
            assert unchanged == negative and not events, 'Signed negative exponent was rewritten'
            skipped += 1
            for exponent, signed in [(['1', '1'], 0), (['1', '1', '0'], 1)]:
                original = fixture(n, width, exponent, signed)
                normalized, events = normalize_cubes(original)
                assert len(events) == 1
                count += 1
                directory = args.output / str(count)
                directory.mkdir(exist_ok=True)
                (directory / 'normalized.json').write_text(json.dumps(normalized) + '\n')
                (directory / 'gold.v').write_text(
                    f'module gold(input [{n - 1}:0] x, output [{width - 1}:0] y);\n'
                    f'wire [{2 * n - 1}:0] square = x * x;\nassign y = square * x;\nendmodule\n')
                script = directory / 'check.ys'
                script.write_text(f'read_verilog {quote(directory / "gold.v")}\n'
                                  f'read_json {quote(directory / "normalized.json")}\n'
                                  'miter -equiv -make_assert -flatten gold top miter\n'
                                  'hierarchy -top miter\ntechmap\nopt\n'
                                  'sat -verify -prove-asserts -show-inputs -show-outputs\n')
                with (directory / 'check.log').open('w') as stream:
                    subprocess.run([executable, '-Q', '-T', '-s', str(script)], stdout=stream,
                                   stderr=subprocess.STDOUT, check=True, timeout=120)
                assert 'SUCCESS!' in (directory / 'check.log').read_text()
    record = {'status': 'pass', 'sat_proved_cube_instances': count, 'negative_exponent_cells_preserved': skipped,
              'scope': 'Unsigned widths 1..6; truncated/exact/widened outputs; unsigned and signed positive-three exponents. Signed negative-one exponents remain exactly unchanged.'}
    (args.output / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()

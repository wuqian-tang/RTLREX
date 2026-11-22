#!/usr/bin/env python3
"""Rebuild arithmetic synthesis inputs from recovered RTL, without case-specific rules."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from arithmetic_lowering import Builder, binary, integer, known_constant, lower
from run_experiment import quote

HERE = Path(__file__).resolve().parent


def normalize_cubes(net):
    """Unsigned x**3 equals (x*x)*x modulo Y_WIDTH, with a full 2*n square."""
    result = copy.deepcopy(net)
    events = []
    for module_name, module in result['modules'].items():
        builder = Builder(module)
        serial = 0
        for name, cell in list(module['cells'].items()):
            if cell['type'] != '$pow':
                continue
            params, conn = cell['parameters'], cell['connections']
            exponent = known_constant(conn['B'])
            if exponent is not None and integer(params['B_SIGNED']) and conn['B'][-1] == '1':
                exponent -= 1 << len(conn['B'])
            if integer(params['A_SIGNED']) or exponent != 3:
                continue
            n, width = len(conn['A']), len(conn['Y'])
            square = list(range(builder.next_bit, builder.next_bit + 2 * n))
            builder.next_bit += 2 * n
            del module['cells'][name]
            for a, b, y in [(conn['A'], conn['A'], square), (square, conn['A'], conn['Y'])]:
                serial += 1
                new_name = '$creas_cube$' + str(serial)
                if new_name in module['cells']:
                    raise ValueError('Cube normalization cell name collision')
                module['cells'][new_name] = {
                    'hide_name': 1, 'type': '$mul', 'attributes': {},
                    'parameters': {'A_SIGNED': binary(0), 'B_SIGNED': binary(0),
                                   'A_WIDTH': binary(len(a)), 'B_WIDTH': binary(len(b)), 'Y_WIDTH': binary(len(y))},
                    'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'},
                    'connections': {'A': a, 'B': b, 'Y': y}}
            events.append({'module': module_name, 'rule': 'unsigned_cube_to_full_square_and_product',
                           'operand_width': n, 'square_width': 2 * n, 'output_width': width})
    return result, events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl-dir', type=Path, default=HERE / 'rtl')
    parser.add_argument('--yosys', default=os.environ.get('YOSYS', 'yosys'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+')
    args = parser.parse_args()
    executable = shutil.which(args.yosys)
    if not executable:
        parser.error('Yosys executable not found')
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error('Output already exists; choose a fresh directory')
    args.output.mkdir(parents=True)
    manifest = json.loads((HERE / 'input_manifest.json').read_text())
    known = {c['case'] for c in manifest['cases']}
    if args.cases and set(args.cases) - known:
        parser.error('Unknown requested case')
    manifest['cases'] = [c for c in manifest['cases'] if not args.cases or c['case'] in args.cases]
    for case in manifest['cases']:
        source = (args.rtl_dir / (case['case'] + '.v')).resolve()
        if hashlib.sha256(source.read_bytes()).hexdigest() != case['recovered_rtl_sha256']:
            raise ValueError('Recovered RTL hash does not match: ' + case['case'])
        raw = args.output / (case['case'] + '.before.json')
        script = args.output / (case['case'] + '.frontend.ys')
        script.write_text(f'read_verilog {quote(source)}\nhierarchy -check -top top\nproc\nflatten\nopt_expr\nopt_clean\nwrite_json {quote(raw)}\n')
        with (args.output / (case['case'] + '.frontend.log')).open('w') as stream:
            subprocess.run([executable, '-Q', '-T', '-s', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        normalized, cubes = normalize_cubes(json.loads(raw.read_text()))
        optimized, rewrites = lower(normalized)
        destination = args.output / (case['case'] + '.json')
        destination.write_text(json.dumps(optimized) + '\n')
        case['published_lowered_json_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
        case['published_lowered_json'] = destination.name
        case['regenerated_input'] = True
        (args.output / (case['case'] + '.lowering.json')).write_text(json.dumps({'cube_normalizations': cubes, 'arithmetic_rewrites': rewrites}, indent=2) + '\n')
        print(case['case'], 'cube normalizations:', len(cubes), 'arithmetic rewrites:', len(rewrites))
    manifest['scope'] = 'Newly regenerated synthesis inputs; retained original recovery proofs do not certify these lowered files.'
    (args.output / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()

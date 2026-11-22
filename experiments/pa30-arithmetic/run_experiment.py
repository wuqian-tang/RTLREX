#!/usr/bin/env python3
"""Map the same frozen PA-30 inputs with the two published uniform profiles."""
import argparse
import concurrent.futures
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
PROFILES = ('timed_original', 'timed_booth')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote(path):
    value = str(path)
    if any(c in value for c in ('"', '\n', '\r', '\\', '$', '[', ']')):
        raise ValueError('Unsupported character in EDA script path: ' + value)
    return '"' + value + '"'


def execute(argv, log, timeout):
    start = time.monotonic()
    with log.open('w') as stream:
        process = subprocess.Popen([str(a) for a in argv], cwd=log.parent,
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            timed_out = True
    record = {'returncode': process.returncode, 'timed_out': timed_out,
              'timeout_seconds': timeout, 'wall_seconds': time.monotonic() - start,
              'log_sha256': sha(log)}
    log.with_suffix('.command.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def tool(value):
    executable = shutil.which(value)
    if not executable:
        raise ValueError('Executable not found: ' + value)
    return Path(executable).resolve()


def measure(args, case, profile):
    output = args.output / case['case'] / profile
    output.mkdir(parents=True)
    original = profile == 'timed_original'
    source = (args.inputs_dir / case['original_gate_input']) if original else args.json_dir / (case['case'] + '.json')
    expected = case['original_gate_sha256'] if original else case['published_lowered_json_sha256']
    if sha(source) != expected:
        raise ValueError('Frozen input hash does not match: ' + str(source))
    result = {'case': case['case'], 'variant': profile, 'source_sha256': sha(source),
              'mapping_status': 'not_run', 'sta_status': 'not_run'}
    script = output / 'synthesis.ys'
    mapped = output / 'mapped.v'
    netlist = output / 'mapped.json'
    frontend = 'read_verilog' if original else 'read_json'
    preparation = ('hierarchy -check -top top\nproc\nflatten\nopt\ntechmap\nopt\ncheck -assert'
                   if original else 'synth -top top -noabc -booth')
    script.write_text(f'{frontend} {quote(source)}\n{preparation}\n'
                      f'abc -exe {quote(args.abc)} -liberty {quote(args.liberty)} -D 2000 -constr {quote(HERE / "abc_constraints.constr")}\n'
                      f'clean\nwrite_verilog -noattr -noexpr -simple-lhs {quote(mapped)}\n'
                      f'write_json {quote(netlist)}\nstat -liberty {quote(args.liberty)}\n')
    record = execute([args.yosys, '-Q', '-T', '-s', script], output / 'synthesis.log', args.synthesis_timeout)
    if record['returncode']:
        result['mapping_status'] = 'timeout' if record['timed_out'] else 'error'
    else:
        net = json.loads(netlist.read_text())['modules']['top']
        unmapped = sorted({c['type'] for c in net['cells'].values() if c['type'].startswith('$')})
        result['mapping_status'] = 'unmapped' if unmapped else 'pass'
        if unmapped:
            result['unmapped_cell_types'] = unmapped
        else:
            area = re.findall(r'Chip area for module.*?:\s*([0-9.]+)', (output / 'synthesis.log').read_text())
            if not area:
                raise ValueError('Yosys log contains no standard-cell area')
            result.update(cell_area_um2=float(area[-1]), cell_count=len(net['cells']), mapped_sha256=sha(mapped),
                          input_bits=sum(len(p['bits']) for p in net['ports'].values() if p['direction'] == 'input'),
                          output_bits=sum(len(p['bits']) for p in net['ports'].values() if p['direction'] == 'output'))
            timing = output / 'timing.tcl'
            timing.write_text(f'''read_liberty {quote(args.liberty)}
read_verilog {quote(mapped)}
link_design top
set_cmd_units -time ns -capacitance pF
create_clock -name virtual_clk -period 10
set_input_delay -clock virtual_clk -max 0 [all_inputs]
set_input_delay -clock virtual_clk -min 0 [all_inputs]
set_output_delay -clock virtual_clk -max 0 [all_outputs]
set_output_delay -clock virtual_clk -min 0 [all_outputs]
set_driving_cell -lib_cell BUF_X1 -input_transition_rise 0.05 -input_transition_fall 0.05 [all_inputs]
set_load 0.01 [all_outputs]
check_setup -verbose
report_checks -path_delay max -format full_clock_expanded -fields {{slew cap fanout input nets}} -digits 6
report_worst_slack -digits 6
report_tns -digits 6
exit
''')
            timing_record = execute([args.sta, '-no_init', '-exit', timing], output / 'timing.log', 60)
            log = (output / 'timing.log').read_text()
            slack = re.findall(r'worst slack\s+([-+0-9.eE]+)', log)
            arrival = re.findall(r'([-+0-9.eE]+)\s+data arrival time', log)
            result['sta_status'] = ('pass' if slack and arrival and not timing_record['returncode'] and 'Error:' not in log
                                    else 'timeout' if timing_record['timed_out'] else 'error')
            if result['sta_status'] == 'pass':
                result.update(worst_slack_ns=float(slack[-1]), max_path_delay_ns=float(arrival[0]))
                assert abs(result['max_path_delay_ns'] + result['worst_slack_ns'] - 10) < 1e-4
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs-dir', type=Path, required=True, help='Original inputs organized as testNN/top_primitive.v')
    parser.add_argument('--json-dir', type=Path, default=HERE / 'synthesis_json', help='Published, hash-matched lowered JSON inputs')
    parser.add_argument('--input-manifest', type=Path, default=HERE / 'input_manifest.json', help='Frozen manifest, or the manifest from prepare_inputs.py')
    parser.add_argument('--liberty', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory, separate from the published data')
    parser.add_argument('--yosys', default=os.environ.get('YOSYS', 'yosys'))
    parser.add_argument('--abc', default=os.environ.get('ABC', 'abc'))
    parser.add_argument('--sta', default=os.environ.get('OPENSTA', os.environ.get('STA', 'sta')))
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--profiles', nargs='+', choices=PROFILES, default=list(PROFILES))
    parser.add_argument('--synthesis-timeout', type=int, default=600)
    args = parser.parse_args()
    if args.jobs < 1 or args.synthesis_timeout < 1:
        parser.error('Jobs and timeout must be positive')
    for field in ('inputs_dir', 'json_dir', 'liberty', 'output'):
        setattr(args, field, getattr(args, field).resolve())
    if args.output.exists():
        parser.error('Output already exists; choose a new directory to preserve prior runs')
    args.output.mkdir(parents=True)
    for field in ('yosys', 'abc', 'sta'):
        setattr(args, field, tool(getattr(args, field)))
    provenance = json.loads((HERE / 'data/provenance.json').read_text())
    if sha(args.liberty) != provenance['library_sha256']:
        parser.error('The Liberty SHA-256 differs from the published experiment')
    versions = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'library_sha256': sha(args.liberty), 'profiles': args.profiles,
                'synthesis_timeout_seconds': args.synthesis_timeout, 'sta_timeout_seconds': 60, 'tools': {}}
    for field, flag in [('yosys', ['-V']), ('abc', ['-c', 'version']), ('sta', ['-version'])]:
        executable = getattr(args, field)
        record = subprocess.run([str(executable)] + flag, text=True, capture_output=True, check=True)
        versions['tools'][field] = {'sha256': sha(executable), 'version': record.stdout.strip()}
    (args.output / 'versions.json').write_text(json.dumps(versions, indent=2) + '\n')
    cases = json.loads(args.input_manifest.read_text())['cases']
    if args.cases:
        unknown = set(args.cases) - {c['case'] for c in cases}
        if unknown:
            parser.error('Unknown cases: ' + ', '.join(sorted(unknown)))
        cases = [c for c in cases if c['case'] in args.cases]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(measure, args, case, profile) for case in cases for profile in args.profiles]
        rows = [future.result() for future in futures]
    columns = sorted({key for row in rows for key in row})
    with (args.output / 'measurements.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row['case'], row['variant'])))


if __name__ == '__main__':
    main()

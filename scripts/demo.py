#!/usr/bin/env python3
"""Run strict positive/negative CEC and exhaustive replay on a synthetic circuit."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New directory for proof logs')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    scripts = root / 'skills' / 'circuit-reverse-rtl' / 'scripts'
    case = root / 'examples' / 'parity'
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tasks = [
        ('equivalent', [str(scripts / 'cec.py'), str(case / 'reference.v'),
                        str(case / 'candidate.v'), '--strict-cec', '--json'], 'pass'),
        ('incorrect', [str(scripts / 'cec.py'), str(case / 'reference.v'),
                       str(case / 'incorrect.v'), '--strict-cec', '--json'], 'fail'),
        ('exhaustive', [str(scripts / 'verify_truth_sim.py'), str(case / 'parity.truth'),
                        str(case / 'candidate.v'), '--json'], 'pass'),
    ]
    summary = {'example': 'synthetic three-input parity', 'llm_calls': 0, 'checks': []}
    # Run outside the checkout to exercise standalone path resolution.
    with tempfile.TemporaryDirectory(prefix='circuit-reverse-demo-') as work:
        for name, command, expected in tasks:
            proc = subprocess.run([sys.executable, *command], cwd=work,
                                  text=True, capture_output=True, timeout=180)
            (out / f'{name}.stdout.json').write_text(proc.stdout)
            (out / f'{name}.stderr.txt').write_text(proc.stderr)
            result = json.loads(proc.stdout)
            if isinstance(result, list):
                if len(result) != 1:
                    raise RuntimeError(f'{name}: unexpected result count')
                result = result[0]
            if result.get('status') != expected:
                raise RuntimeError(f'{name}: expected {expected}, got {result}')
            if expected == 'pass' and proc.returncode != 0:
                raise RuntimeError(f'{name}: checker returned an error')
            summary['checks'].append({'name': name, 'status': result['status'],
                                      'expected': expected, 'returncode': proc.returncode})
    summary['status'] = 'pass'
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

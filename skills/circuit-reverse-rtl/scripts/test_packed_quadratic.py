#!/usr/bin/env python3
"""Fresh generated polynomial controls; never read benchmark/private specs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from truth.integer_models import infer_integer_model, infer_packed_quadratic, probes, solve_power_two_congruence

SEED = 0xD14A20261006


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signed(value: int, width: int) -> int:
    return value - (1 << width) if value & (1 << (width - 1)) else value


def write_truth(path: Path, n: int, m: int, words: list[int]) -> None:
    mask = (1 << n) - 1
    path.write_text('\n'.join(''.join(str((words[index ^ mask] >> bit) & 1)
                                    for index in range(1 << n)) for bit in range(m)) + '\n')


def run_json(command: list[str]) -> tuple[object, float]:
    start = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f'Control failed: {command}\n{result.stdout}\n{result.stderr}')
    return json.loads(result.stdout), time.monotonic() - start


def congruence_controls() -> int:
    checked = 0
    for width in range(1, 10):
        modulus = 1 << width
        for multiplier in range(-19, 20):
            image = {(multiplier * q) % modulus for q in range(modulus)}
            for rhs in range(modulus):
                solution = solve_power_two_congruence(multiplier, rhs, width)
                assert (solution is not None) == (rhs in image), (width, multiplier, rhs)
                if solution is not None:
                    assert multiplier * solution % modulus == rhs
                checked += 1
    return checked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--yosys', required=True, type=Path)
    parser.add_argument('--baseline-model', type=Path, help='Optional earlier integer_models.py for comparison')
    args = parser.parse_args()
    assert not args.out.exists(), 'Preserve all previously recorded control evidence'
    args.out.mkdir(parents=True)
    baseline = None
    if args.baseline_model:
        baseline = {}
        exec(compile(args.baseline_model.read_text(), str(args.baseline_model), 'exec'), baseline)
    congruence_cases = congruence_controls()
    randomizer = random.Random(SEED)
    rows = []
    shapes = ((1, 2, 3), (2, 1, 1), (2, 2, 9), (2, 5, 3), (5, 2, 13),
              (3, 4, 17), (4, 3, 6), (5, 5, 12), (7, 2, 24), (2, 7, 2), (3, 2, 32))
    start_all = time.monotonic()
    for a_width, b_width, m in shapes:
        for a_signed, b_signed in ((False, False), (True, True), (True, False), (False, True)):
            index, n = len(rows), a_width + b_width
            coefficients = [randomizer.randrange(-(1 << m), 1 << m) for _ in range(6)]
            # Force square/cross terms on each control while still permitting
            # modular/one-bit degeneracy. Both positive and negative overflows
            # are exercised by the complete domain, not selected examples.
            for position in (3, 4, 5):
                coefficients[position] |= 1
            c0, c1, c2, c3, c4, c5 = coefficients
            words = []
            for x in range(1 << n):
                a, b = x & ((1 << a_width) - 1), x >> a_width
                a = signed(a, a_width) if a_signed else a
                b = signed(b, b_width) if b_signed else b
                words.append((c0 + c1*a + c2*b + c3*a*a + c4*a*b + c5*b*b) & ((1 << m) - 1))
            started = time.monotonic()
            old = baseline['infer_integer_model'](n, m, words) if baseline else None
            old_seconds = time.monotonic() - started
            started = time.monotonic()
            model = infer_integer_model(n, m, words)
            infer_seconds = time.monotonic() - started
            assert model is not None, (index, a_width, b_width, m, a_signed, b_signed)
            name = f'control_{index:03d}'
            truth, candidate = args.out / f'{name}.truth', args.out / f'{name}.v'
            write_truth(truth, n, m, words)
            candidate.write_text(model[1])
            proof, proof_seconds = run_json([sys.executable, str(SCRIPTS / 'verify_truth_yosys.py'),
                                            str(truth), str(candidate), '--yosys', str(args.yosys.resolve()),
                                            '--no-cache', '--json'])
            assert proof['status'] == 'pass' and proof['frontend'] == 'pass', proof
            independent, independent_seconds = run_json([sys.executable, str(SCRIPTS / 'verify_truth_sim.py'),
                                                         str(truth), str(candidate), '--json'])
            assert independent['status'] == 'pass' and independent['vectors'] == 1 << n, independent
            cost, cost_seconds = run_json([sys.executable, str(SCRIPTS / 'RTL_cost_calculator.py'),
                                          str(candidate), '--json', '--detail'])
            row = {'control': name, 'n_inputs': n, 'n_outputs': m,
                   'a_width': a_width, 'b_width': b_width, 'a_signed': a_signed, 'b_signed': b_signed,
                   'generated_coefficients': coefficients, 'seed': SEED,
                   'baseline_family': old[0] if old else None, 'baseline_infer_seconds': old_seconds,
                   'prototype_family': model[0], 'prototype_infer_seconds': infer_seconds,
                   'cost': cost[0]['cost'], 'cost_seconds': cost_seconds,
                   'truth_sha256': digest(truth), 'candidate_sha256': digest(candidate),
                   'fixed_yosys_proof': proof, 'fixed_yosys_seconds': proof_seconds,
                   'independent_icarus_proof': independent, 'independent_icarus_seconds': independent_seconds}
            rows.append(row)
            (args.out / f'{name}.json').write_text(json.dumps(row, indent=2) + '\n')
    # A deliberate mutation outside the candidate-identifying/probe subset
    # demonstrates that probe agreement cannot certify a polynomial.
    n, m, split = 9, 12, 4
    words = [(17 + 7*(x & 15) - 11*(x >> split) + 5*(x & 15)**2
              + 9*(x & 15)*(x >> split) - 3*(x >> split)**2) & ((1 << m) - 1)
             for x in range(1 << n)]
    assert infer_packed_quadratic(n, m, words) is not None
    reserved = set(probes(len(words))) | {0, 1, 2, 1 << split, 2 << split, 1 | (1 << split)}
    mutation = next(x for x in range(len(words)) if x not in reserved)
    words[mutation] ^= 1
    assert infer_packed_quadratic(n, m, words) is None, 'Full-domain mismatch must reject the model'
    summary = {'schema': 'prototype-packed-quadratic-controls/v1', 'seed': SEED,
               'scope': 'Fresh self-generated polynomial controls; not external heldout or official matched trials',
               'congruence_equations_checked': congruence_cases,
               'generated_controls': len(rows), 'baseline_model_supplied': args.baseline_model is not None,
               'baseline_matched': sum(r['baseline_family'] is not None for r in rows) if baseline else None,
               'prototype_matched': len(rows), 'yosys_complete_domain_passes': len(rows),
               'independent_icarus_complete_domain_passes': len(rows),
               'outside_probe_mutation_rejected': {'input': mutation, 'n_inputs': n, 'n_outputs': m},
               'total_seconds': time.monotonic() - start_all,
               'infer_seconds_sum': sum(r['prototype_infer_seconds'] for r in rows),
               'cost_min': min(r['cost'] for r in rows), 'cost_max': max(r['cost'] for r in rows),
               'implementation_sha256': digest(SCRIPTS / 'truth' / 'integer_models.py'),
               'test_sha256': digest(Path(__file__)), 'rows': rows}
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: value for key, value in summary.items() if key != 'rows'}, indent=2))


if __name__ == '__main__':
    main()

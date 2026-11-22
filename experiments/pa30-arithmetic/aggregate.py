#!/usr/bin/env python3
"""Recompute the published paired arithmetic means without EDA tools."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent


def aggregate(measurements):
    with measurements.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    index = {(row['case'], row['variant']): row for row in rows}
    if len(index) != len(rows):
        raise ValueError('Duplicate case/profile measurements')
    cases = sorted({row['case'] for row in rows})
    profiles = ['timed_original', 'timed_booth']
    if set(index) != {(case, profile) for case in cases for profile in profiles}:
        raise ValueError('Missing or unexpected case/profile measurement')
    good = lambda r: r['mapping_status'] == 'pass' and r['sta_status'] == 'pass'
    paired = [case for case in cases if all(good(index[case, p]) for p in profiles)]
    if not paired:
        raise ValueError('No completed paired cases')
    result = {'cases': len(cases), 'paired_cases': paired, 'n': len(paired), 'metrics': {}}
    for field in ('cell_area_um2', 'max_path_delay_ns'):
        pairs = [(float(index[c, profiles[0]][field]), float(index[c, profiles[1]][field])) for c in paired]
        ref, opt = mean(a for a, b in pairs), mean(b for a, b in pairs)
        result['metrics'][field] = {'reference_mean': ref, 'optimized_mean': opt,
                                    'change_percent': 100 * (opt / ref - 1),
                                    'lower': sum(b < a for a, b in pairs),
                                    'equal': sum(b == a for a, b in pairs),
                                    'higher': sum(b > a for a, b in pairs)}
    result['both_metrics_lower_or_equal'] = sum(
        all(float(index[c, profiles[1]][f]) <= float(index[c, profiles[0]][f])
            for f in ('cell_area_um2', 'max_path_delay_ns')) for c in paired)
    for profile, key in zip(profiles, ('original', 'optimized')):
        result[key + '_completed'] = sum(good(index[c, profile]) for c in cases)
        result[key + '_timeouts'] = [c for c in cases if index[c, profile]['mapping_status'] == 'timeout']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measurements', type=Path, default=HERE / 'data/measurements.csv')
    parser.add_argument('--verify-published', action='store_true')
    args = parser.parse_args()
    result = aggregate(args.measurements)
    if args.verify_published:
        expected = json.loads((HERE / 'data/summary.json').read_text())
        for key in result:
            if key == 'metrics':
                for metric, record in result[key].items():
                    for field, value in record.items():
                        assert math.isclose(value, expected[key][metric][field], rel_tol=1e-12, abs_tol=1e-12), (metric, field)
            else:
                assert result[key] == expected[key], key
        manifest = json.loads((HERE / 'input_manifest.json').read_text())
        for case in manifest['cases']:
            for path_key, hash_key in [('recovered_rtl', 'recovered_rtl_sha256'),
                                       ('published_lowered_json', 'published_lowered_json_sha256')]:
                path = HERE / case[path_key]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == case[hash_key], path
        hashes = json.loads((HERE / 'sha256_manifest.json').read_text())['files']
        for filename, digest in hashes.items():
            path = HERE / filename
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path
        print(f'PASS: all published means, counts, 60 input hashes, and {len(hashes)} package file hashes match')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

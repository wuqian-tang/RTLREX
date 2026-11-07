#!/usr/bin/env python3
"""Check historical receipt identities; does not replay the original proofs."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    cases={r['case']:r for r in json.loads((ROOT/'input_manifest.json').read_text())['cases']}
    rows=json.loads((ROOT/'proof_records/index.json').read_text())['records']
    if len(rows)!=30 or {r['case'] for r in rows}!=set(cases):raise ValueError('Proof receipt coverage mismatch')
    for row in rows:
        p=ROOT/row['path'];record=json.loads(p.read_text());expected=cases[row['case']]
        pairs=[(hashlib.sha256(p.read_bytes()).hexdigest(),row['sha256']),
               (record['case'],row['case']),
               (record['original_record_sha256'],row['original_record_sha256']),
               (record['original_record_sha256'],expected['retained_recovery_proof_record_sha256']),
               (record['reference_sha256'],expected['original_gate_sha256']),
               (record['candidate_sha256'],expected['recovered_rtl_sha256']),
               (record['engine'],expected['retained_recovery_proof_engine']),
               (hashlib.sha256((ROOT/expected['recovered_rtl']).read_bytes()).hexdigest(),record['candidate_sha256'])]
        if any(a!=b for a,b in pairs):raise ValueError('Proof receipt mismatch: '+row['case'])
    print('PASS: 30 historical proof receipts match frozen source/candidate/record identities. No proof rerun.')
if __name__=='__main__':main()

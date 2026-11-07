#!/usr/bin/env python3
"""Check the current installable Skill inventory (not the historical TT snapshot)."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'docs/SOURCE_PROVENANCE.json'

def inventory():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT/'skills/circuit-reverse-rtl').rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'
            and p.name not in {'tool_paths.env','fast_primitive_sampler'}}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true',help='Explicitly regenerate after reviewed source changes')
    parser.add_argument('--version',default='0.1.0-rc2')
    args=parser.parse_args();actual=inventory()
    if args.write:
        record={'schema':'rtlrex-current-source-provenance/v1','release':args.version,
                'scope':'Current portable installable Skill; distinct from frozen evaluated Skill in experiments/tt100-final/evaluated_skill.',
                'historical_export_manifest':'docs/history/source-provenance-0.1.0-rc1.json',
                'files':[{'path':p,'release_sha256':s} for p,s in actual.items()]}
        MANIFEST.write_text(json.dumps(record,indent=2)+'\n')
    expected={r['path']:r['release_sha256'] for r in json.loads(MANIFEST.read_text())['files']}
    changed=[p for p in actual if p in expected and actual[p]!=expected[p]]
    report={'files':len(actual),'changed':changed,'unlisted':sorted(actual.keys()-expected.keys()),'missing':sorted(expected.keys()-actual.keys())}
    print(json.dumps(report,indent=2))
    return int(bool(changed or report['unlisted'] or report['missing']))

if __name__=='__main__':raise SystemExit(main())

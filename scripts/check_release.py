#!/usr/bin/env python3
"""Check the export boundary; this is a pattern scan, not an ownership audit."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if (root / '.git').exists():
        names = subprocess.check_output(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
            cwd=root).split(b'\0')
        paths = [root / n.decode() for n in names if n]
    else:
        ignored = {'.git', '__pycache__', '.venv', 'outputs', '.codex_skill_cache'}
        paths = [p for p in root.rglob('*') if p.is_file()
                 and not ignored.intersection(p.relative_to(root).parts)]
    source_path = root / 'benchmarks/tt100/source.json'
    licensed_inputs = {}
    if source_path.exists():
        source = json.loads(source_path.read_text())
        licensed_inputs = {root / 'benchmarks/tt100' / row['path']: row['sha256']
                           for row in source['inputs']}
    issues = [] if paths else [['.', 'no export files found']]
    blocked_dirs = {'experimental_results', 'paper_preparation', 'benchmarks_ICCAD22', 'external'}
    patterns = {
        'credential': re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{32,})'),
        'private key': re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
        'personal home path': re.compile(r'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
    }
    for path in paths:
        rel = path.relative_to(root)
        if path.is_symlink():
            issues.append([str(rel), 'symlink'])
            continue
        if blocked_dirs.intersection(rel.parts) or path.name in {'overleaf.config', 'tool_paths.env', '.env'}:
            issues.append([str(rel), 'private/generated path'])
        data = path.read_bytes()
        known_truth = (path in licensed_inputs and
                       hashlib.sha256(data).hexdigest() == licensed_inputs[path])
        if data.startswith(b'\x7fELF') or b'\0' in data or (len(data) > 2_000_000 and not known_truth):
            issues.append([str(rel), 'binary or oversized export'])
            continue
        text = data.decode('utf-8')
        for kind, pattern in patterns.items():
            if pattern.search(text):
                issues.append([str(rel), kind])
    print(json.dumps({'status': 'fail' if issues else 'pass', 'files_checked': len(paths),
                      'issues': issues, 'scope': 'Tracked and nonignored untracked files; never scans or exports Git credentials.'}, indent=2))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())

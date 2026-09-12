#!/usr/bin/env python3
"""Report runtime dependencies without installing software or calling an LLM."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-all', action='store_true')
    args = parser.parse_args()
    options = {
        'YOSYS': ('yosys',), 'ABC': ('abc', 'berkeley-abc', 'yosys-abc'),
        'YOSYS_SMTBMC': ('yosys-smtbmc',), 'Z3': ('z3',),
        'IVERILOG': ('iverilog',), 'VVP': ('vvp',), 'CXX': ('g++',),
    }
    found = {}
    for key, defaults in options.items():
        override = os.environ.get(key) if key in {'YOSYS', 'ABC', 'YOSYS_SMTBMC'} else None
        names = (override,) if override else defaults
        found[key] = next((p for name in names if (p := shutil.which(name))), None)
    report = {'python': sys.version.split()[0], 'python_supported': sys.version_info >= (3, 10),
              'tools': found, 'numpy_available': importlib.util.find_spec('numpy') is not None,
              'note': 'Paths are local diagnostics. Tool presence does not establish backend compatibility.'}
    print(json.dumps(report, indent=2))
    required = found.values() if args.require_all else (found['YOSYS'], found['ABC'])
    return 0 if report['python_supported'] and all(required) else 1


if __name__ == '__main__':
    raise SystemExit(main())

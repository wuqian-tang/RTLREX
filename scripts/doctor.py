#!/usr/bin/env python3
"""Report runtime dependencies without installing software or calling an LLM."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import shutil


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/circuit-reverse-rtl/scripts"))
from verify.tooling import optional_tool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-all', action='store_true')
    args = parser.parse_args()
    keys = ('YOSYS', 'ABC', 'YOSYS_SMTBMC', 'Z3', 'IVERILOG', 'VVP', 'CXX')
    found = {key: optional_tool(key) for key in keys if key != 'Z3'}
    # yosys-smtbmc launches z3 by name, so it must really be available on PATH.
    found['Z3'] = shutil.which('z3')
    report = {'python': sys.version.split()[0], 'python_supported': sys.version_info >= (3, 10),
              'tools': found, 'numpy_available': importlib.util.find_spec('numpy') is not None,
              'note': 'Paths are local diagnostics. Tool presence does not establish backend compatibility.'}
    print(json.dumps(report, indent=2))
    required = found.values() if args.require_all else (found['YOSYS'], found['ABC'])
    return 0 if report['python_supported'] and all(required) else 1


if __name__ == '__main__':
    raise SystemExit(main())

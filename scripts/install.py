#!/usr/bin/env python3
"""Copy the self-contained Skill to an explicitly selected, new directory."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', required=True, type=Path,
                        help='New skill directory, including circuit-reverse-rtl')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / 'skills' / 'circuit-reverse-rtl'
    destination = args.dest.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        parser.error('destination already exists; choose a new directory or move your old installation first')
    if destination == source or source in destination.parents:
        parser.error('destination cannot be inside the source skill')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(
        '__pycache__', '*.pyc', 'tool_paths.env', 'fast_primitive_sampler'))
    for name in ('LICENSE', 'NOTICE.md'):
        if (root / name).is_file():
            shutil.copy2(root / name, destination / name)
    print(f'Installed {destination}')
    print('Configure Yosys/ABC via PATH or YOSYS/ABC environment variables.')


if __name__ == '__main__':
    main()

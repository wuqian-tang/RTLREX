#!/usr/bin/env python3
"""Download the pinned Nangate45 library and preserve its upstream license."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

REV = 'd26bf27e1467d4ac903655694ac31e2ec3f85260'
BASE = f'https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/{REV}/flow/platforms/nangate45/'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    files = {'lib/NangateOpenCellLibrary_typical.lib': '8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1',
             'LICENSE': '0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594',
             'README.md': '0e3c8a8cbe5429552764c6531dc454d64f6aa7c1f7128175b5f06070a3de578d'}
    for source, digest in files.items():
        with urllib.request.urlopen(BASE + source, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Downloaded library dependency failed SHA-256 check: ' + source)
        (args.output / Path(source).name).write_bytes(data)
    raw = (args.output / 'NangateOpenCellLibrary_typical.lib').read_text()
    declaration = '  default_wire_load : "5K_hvratio_1_1" ;'
    assert raw.count(declaration) == 1
    derived = raw.replace(declaration, '  /* Experiment: default wire-load disabled; no interconnect parasitics. */')
    assert hashlib.sha256(derived.encode()).hexdigest() == '244792ed3c47d9e3c0c1127089f229e6daa249a882e2bb1230ee5fcf87bceaad'
    target = args.output / 'NangateOpenCellLibrary_typical_no_wireload.lib'
    target.write_text(derived)
    print(target)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Compatibility entry point for sampling.fast_sampler."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sampling.fast_sampler import *  # noqa: F401,F403


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist")
    args = parser.parse_args()
    vectors = [json.loads(line) for line in sys.stdin if line.strip()]
    for row in sample_many(args.netlist, vectors):
        print(json.dumps(row, sort_keys=True))

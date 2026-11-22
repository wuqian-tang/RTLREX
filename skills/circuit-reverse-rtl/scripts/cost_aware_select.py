#!/usr/bin/env python3
"""Compatibility entry point for rewriting.cost_aware_select."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rewriting.cost_aware_select import *  # noqa: F401,F403
from rewriting.cost_aware_select import main


if __name__ == "__main__":
    raise SystemExit(main())

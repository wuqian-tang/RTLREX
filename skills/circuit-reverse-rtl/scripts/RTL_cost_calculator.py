#!/usr/bin/env python3
"""Compatibility entry point for cost.RTL_cost_calculator."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cost.RTL_cost_calculator import *  # noqa: F401,F403
from cost.RTL_cost_calculator import main


if __name__ == "__main__":
    raise SystemExit(main())

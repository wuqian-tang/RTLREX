#!/usr/bin/env python3
"""Compatibility entry point for verify.cec."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify.cec import *  # noqa: F401,F403
from verify.cec import main


if __name__ == "__main__":
    raise SystemExit(main())

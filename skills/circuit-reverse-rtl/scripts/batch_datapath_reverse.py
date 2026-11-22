#!/usr/bin/env python3
"""Compatibility entry point for reverse.batch_datapath_reverse."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reverse.batch_datapath_reverse import *  # noqa: F401,F403
from reverse.batch_datapath_reverse import main


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Shared syntax-cost evaluator only, using the frozen common CSV weights."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'scripts'))
from cost.RTL_cost_calculator import main
if __name__ == '__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Fixed-frontend exhaustive Icarus CLI; lowered replay API is internal."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify.truth_parallel import run_one

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('truth',type=Path);parser.add_argument('verilog',nargs='+',type=Path)
    parser.add_argument('--input-port',default='x');parser.add_argument('--output-port',default='y')
    parser.add_argument('--compile-timeout',type=int,default=120)
    parser.add_argument('--run-timeout',type=float,default=180)
    parser.add_argument('--replay-workers',type=int,help='1–4; default one worker below 12 input bits, four otherwise')
    parser.add_argument('--json',action='store_true');args=parser.parse_args()
    from verify.truth_yosys import verify, default_yosys
    if (args.input_port,args.output_port)!=('x','y'):
        parser.error('The exact checked interface is module top with unsigned x/y ports')
    rows=[verify(args.truth,rtl,default_yosys(),compile_timeout=args.compile_timeout,
        run_timeout=args.run_timeout,use_cache=False,use_bitparallel=False,
        replay_workers=args.replay_workers) for rtl in args.verilog]
    if args.json:print(json.dumps(rows if len(rows)!=1 else rows[0],indent=2,sort_keys=True))
    else:
        for row in rows:print(f"{row['status'].upper()} {row.get('verilog','')} vectors={row.get('vectors')}")
    return 0 if all(row['status']=='pass' for row in rows) else 1
if __name__=='__main__':raise SystemExit(main())

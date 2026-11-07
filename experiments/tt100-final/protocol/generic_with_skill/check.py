#!/usr/bin/env python3
"""Shared validation only: no function identification, RTL emitter, or recognizer."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'scripts'))
from verify.truth_yosys import verify, default_yosys
if __name__ == '__main__':
    try:
        result=verify(Path(sys.argv[1]),Path(sys.argv[2]),default_yosys(),use_cache=False)
    except Exception as error:
        result={'status':'checker_error','error':f'{type(error).__name__}: {error}'}
    print(json.dumps(result));sys.exit(0 if result.get('status')=='pass' else 1)

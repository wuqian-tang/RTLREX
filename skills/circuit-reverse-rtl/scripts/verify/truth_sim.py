#!/usr/bin/env python3
"""Exhaustively verify ``module top(input x, output y)`` against a .truth file."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truth.utils import read_truth_words


from verify.tooling import optional_tool

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", help="Input .truth file")
    parser.add_argument("verilog", nargs="+", help="Candidate Verilog file(s)")
    parser.add_argument("--input-port", default="x")
    parser.add_argument("--output-port", default="y")
    parser.add_argument("--json", action="store_true", help="Print JSON result rows")
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=180)
    return parser.parse_args()


def run_one(
    truth: Path,
    verilog: Path,
    input_port: str,
    output_port: str,
    compile_timeout: int,
    run_timeout: int,
) -> Dict[str, object]:
    n_in, n_out, expected = read_truth_words(truth)
    iverilog = optional_tool("IVERILOG")
    vvp = optional_tool("VVP")
    if not iverilog or not vvp:
        return {
            "status": "tool_missing",
            "truth": str(truth),
            "verilog": str(verilog),
            "error": "iverilog or vvp not found",
        }

    with tempfile.TemporaryDirectory(prefix="truth_sim_") as tmp:
        tmpdir = Path(tmp)
        tb = tmpdir / "tb.v"
        simv = tmpdir / "simv"
        truth_literal = str(truth.resolve()).replace("\\", "\\\\").replace('"', '\\"')
        tb.write_text(
            "module tb;\n"
            f"  reg [{n_in - 1}:0] {input_port};\n"
            f"  wire [{n_out - 1}:0] {output_port};\n"
            f"  reg [{(1 << n_in) - 1}:0] __truth_bits [0:{n_out - 1}];\n"
            f"  reg [{n_out - 1}:0] __expected;\n"
            "  integer __truth_index;\n"
            "  integer __truth_bit;\n"
            f"  top dut(.{input_port}({input_port}), .{output_port}({output_port}));\n"
            "  initial begin\n"
            f'    $readmemb("{truth_literal}", __truth_bits);\n'
            f"    for (__truth_index = 0; __truth_index < {1 << n_in}; "
            "__truth_index = __truth_index + 1) begin\n"
            f"      {input_port} = __truth_index[{n_in - 1}:0];\n"
            "      #1;\n"
            f"      for (__truth_bit = 0; __truth_bit < {n_out}; "
            "__truth_bit = __truth_bit + 1)\n"
            "        __expected[__truth_bit] = __truth_bits[__truth_bit][__truth_index];\n"
            f"      if ({output_port} !== __expected) begin\n"
            f'        $display("TRUTH_SIM_MISMATCH index=%0d got=%h expected=%h", '
            f"__truth_index, {output_port}, __expected);\n"
            "        $finish(0);\n"
            "      end\n"
            "    end\n"
            f'    $display("TRUTH_SIM_PASS vectors={1 << n_in}");\n'
            "    $finish(0);\n"
            "  end\n"
            "endmodule\n"
        )
        try:
            compile_proc = subprocess.run(
                [iverilog, "-g2012", "-o", str(simv), str(verilog), str(tb)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=compile_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "compile_timeout", "truth": str(truth), "verilog": str(verilog)}
        if compile_proc.returncode != 0:
            return {
                "status": "compile_fail",
                "truth": str(truth),
                "verilog": str(verilog),
                "error": (compile_proc.stdout + compile_proc.stderr).strip(),
            }
        try:
            run_proc = subprocess.run(
                [vvp, str(simv)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=run_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "run_timeout", "truth": str(truth), "verilog": str(verilog)}
        if run_proc.returncode != 0:
            return {
                "status": "run_fail",
                "truth": str(truth),
                "verilog": str(verilog),
                "error": (run_proc.stdout + run_proc.stderr).strip(),
            }
        mismatch = re.search(
            r"TRUTH_SIM_MISMATCH index=(\d+) got=([0-9a-fA-FxXzZ]+) expected=([0-9a-fA-FxXzZ]+)",
            run_proc.stdout,
        )
        if mismatch:
            return {
                "status": "mismatch",
                "truth": str(truth),
                "verilog": str(verilog),
                "index": int(mismatch.group(1)),
                "got": mismatch.group(2),
                "expected": mismatch.group(3),
            }
        pass_marker = f"TRUTH_SIM_PASS vectors={len(expected)}"
        output_lines = [line.strip() for line in run_proc.stdout.splitlines() if line.strip()]
        if output_lines != [pass_marker]:
            return {
                "status": "short_output",
                "truth": str(truth),
                "verilog": str(verilog),
                "detail": run_proc.stdout[-500:],
            }
    return {
        "status": "pass",
        "truth": str(truth),
        "verilog": str(verilog),
        "vectors": len(expected),
        "n_inputs": n_in,
        "n_outputs": n_out,
    }


def main() -> int:
    args = parse_args()
    truth = Path(args.truth)
    rows = [
        run_one(
            truth,
            Path(verilog),
            args.input_port,
            args.output_port,
            args.compile_timeout,
            args.run_timeout,
        )
        for verilog in args.verilog
    ]
    if args.json:
        print(json.dumps(rows if len(rows) != 1 else rows[0], indent=2, sort_keys=True))
    else:
        for row in rows:
            detail = f" vectors={row.get('vectors')}" if row.get("status") == "pass" else f" detail={row.get('detail') or row.get('error') or ''}"
            print(f"{row['status'].upper()} {row['verilog']}{detail}")
    return 0 if all(row["status"] == "pass" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

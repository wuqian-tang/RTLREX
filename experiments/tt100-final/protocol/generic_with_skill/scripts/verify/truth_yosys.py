#!/usr/bin/env python3
"""Check a truth table against RTL accepted and lowered by the Yosys frontend.

The single pass result requires the fixed Yosys frontend, the exact combinational
interface, and complete-domain replay of its lowered circuit. Supported JSON
cells use bit-parallel replay; other cells use exhaustive Verilog simulation.
An optional authenticated local cache reuses only the same complete evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify.truth_sim import run_one
from verify import truth_verification_cache as cache
from verify import truth_parallel


def executable(value: str | Path) -> Path | None:
    value = str(value)
    path = Path(value).expanduser()
    if not path.is_absolute() and len(path.parts) == 1:
        found = shutil.which(value)
        if found:
            path = Path(found)
    return path.resolve() if path.is_file() and os.access(path, os.X_OK) else None


def default_yosys() -> Path:
    configured = os.environ.get("YOSYS")
    if configured and (found := executable(configured)):
        return found
    tool_config = Path(__file__).resolve().parents[1] / "tool_paths.env"
    if tool_config.is_file():
        for line in tool_config.read_text().splitlines():
            if line.startswith("YOSYS="):
                value = line.split("=", 1)[1].strip().strip('"\'')
                if found := executable(value):
                    return found
    found = shutil.which("yosys")
    if found:
        return Path(found).resolve()
    for parent in Path(__file__).resolve().parents:
        if found := executable(parent / "external/yosys/yosys"):
            return found
    return Path("yosys")


def truth_dimensions(data: bytes) -> tuple[int, int]:
    lines = [line.strip() for line in data.decode().splitlines() if line.strip()]
    if not lines or len(lines[0]) < 2 or len(lines[0]) & (len(lines[0]) - 1):
        raise ValueError("Truth rows must have power-of-two length of at least two")
    if any(len(line) != len(lines[0]) or set(line) - {"0", "1"} for line in lines):
        raise ValueError("Truth rows must have equal lengths and binary characters")
    return len(lines[0]).bit_length() - 1, len(lines)


def check_interface(path: Path, n_inputs: int, n_outputs: int) -> dict:
    try:
        modules = json.loads(path.read_text())["modules"]
        ports = modules["top"]["ports"]
        issues = []
        if set(ports) != {"x", "y"}:
            issues.append("Top interface must contain exactly x and y")
        for name, direction, width in (("x", "input", n_inputs), ("y", "output", n_outputs)):
            port = ports.get(name, {})
            if port.get("direction") != direction or len(port.get("bits", [])) != width:
                issues.append(f"{name} must be {direction} [{width - 1}:0]")
            if port.get("offset", 0) or port.get("upto", 0) or port.get("signed", 0):
                issues.append(f"{name} must have an unsigned descending zero-offset packed range")
        state = [f"{module}/{name}:{cell['type']}"
                 for module, data in modules.items() for name, cell in data.get("cells", {}).items()
                 if re.search(r"dff|latch|\$ff|mem", cell.get("type", ""), re.I)]
        if state:
            issues.append("State or memory cells are not permitted")
        for module, data in modules.items():
            if data.get("memories") or data.get("processes"):
                issues.append(f"{module}: unresolved memories or processes are not permitted")
            attributes = data.get("attributes", {})
            if any(str(attributes.get(key, 0)).strip("0") for key in ("blackbox", "whitebox")):
                issues.append(f"{module}: blackbox or whitebox modules are not permitted")
        return {"status": "fail" if issues else "pass", "issues": issues,
                "ports": ports, "state_or_memory_cells": state}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"status": "unknown", "issues": ["Missing or malformed frontend interface export"]}


def verify(
    truth: Path,
    candidate: Path,
    yosys: Path,
    *,
    frontend_timeout: int = 120,
    compile_timeout: int = 120,
    run_timeout: int = 180,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    use_bitparallel: bool = True,
    replay_workers: int | None = None,
) -> dict[str, object]:
    truth = truth.resolve()
    candidate = candidate.resolve()
    yosys = executable(yosys) or yosys.resolve()
    result: dict[str, object] = {
        "truth": str(truth),
        "verilog": str(candidate),
        "checker": "Yosys frontend plus complete-domain replay of its lowered circuit",
    }
    if not truth.is_file() or not candidate.is_file() or not yosys.is_file():
        return {**result, "status": "input_missing"}
    truth_bytes, candidate_bytes = truth.read_bytes(), candidate.read_bytes()
    result["truth_sha256"] = hashlib.sha256(truth_bytes).hexdigest()
    result["candidate_sha256"] = hashlib.sha256(candidate_bytes).hexdigest()
    try:
        n_inputs, n_outputs = truth_dimensions(truth_bytes)
    except (ValueError, UnicodeError) as error:
        return {**result, "status": "invalid_truth", "error": str(error)}
    if replay_workers is not None and (type(replay_workers) is not int or not 1 <= replay_workers <= 4):
        return {**result, "status": "invalid_workers"}
    effective_workers = min(1 << n_inputs, replay_workers if replay_workers is not None else (1 if n_inputs < 12 else 4))
    result["replay_workers"] = effective_workers
    cache_root = cache_dir
    if cache_root is None and os.environ.get("CIRCUIT_REVERSE_SKILL_CACHE"):
        cache_root = Path(os.environ["CIRCUIT_REVERSE_SKILL_CACHE"]) / "truth_frontend"
    tools = {"yosys": yosys}
    for name in ("iverilog", "vvp"):
        if path := shutil.which(name):
            tools[name] = Path(path).resolve()
    sources = [Path(__file__), Path(truth_parallel.__file__), Path(cache.__file__),
               Path(__file__).with_name("truth_sim.py"),
               Path(__file__).parents[1] / "truth/utils.py"]
    bitparallel = None
    bitparallel_source = Path(__file__).with_name("truth_bitparallel.py")
    if use_bitparallel and bitparallel_source.is_file():
        from verify.truth_bitparallel import check_json
        bitparallel = check_json
        sources.append(bitparallel_source)
    result["checker_sha256"] = {str(path.resolve()): cache.digest(path.read_bytes()) for path in sources}
    result["frontend_flow"] = "read_verilog; hierarchy -check -top top; proc; opt; check -assert; write_verilog -noattr"
    result["auxiliary_export"] = "write_json after fixed frontend flow; no additional passes"
    manifest = None
    if use_cache and cache_root is not None and len(tools) == 3 and cache.eligible(candidate_bytes):
        try:
            manifest = cache.identity(truth_bytes, candidate_bytes, tools, sources,
                                      (frontend_timeout, compile_timeout, run_timeout),
                                      {"use_bitparallel": use_bitparallel, "replay_workers": effective_workers})
        except OSError:
            pass
    if manifest is not None:
        prior = cache.load(cache_root, manifest)
        if prior is not None:
            if truth.read_bytes() != truth_bytes or candidate.read_bytes() != candidate_bytes:
                return {**result, "status": "input_changed", "cache": "rejected"}
            return {**prior, "truth": str(truth), "verilog": str(candidate), "cache": "hit"}
        result["cache"] = "miss"

    with tempfile.TemporaryDirectory(prefix="truth_yosys_") as temporary:
        directory = Path(temporary)
        source = directory / "candidate.v"
        lowered = directory / "lowered.v"
        design = directory / "frontend.json"
        source.write_bytes(candidate_bytes)
        truth_snapshot = directory / "input.truth"
        truth_snapshot.write_bytes(truth_bytes)
        script = (
            f"read_verilog {source}; hierarchy -check -top top; "
            f"proc; opt; check -assert; write_verilog -noattr {lowered}; write_json {design}"
        )
        try:
            frontend = subprocess.run(
                [str(yosys), "-Q", "-T", "-p", script],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=frontend_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {**result, "status": "frontend_timeout", "frontend": "timeout"}
        if frontend.returncode != 0 or not lowered.is_file():
            diagnostics = (frontend.stdout + frontend.stderr).strip().splitlines()
            return {
                **result,
                "status": "frontend_fail",
                "frontend": "fail",
                "error": "\n".join(diagnostics[-12:]),
            }

        result["frontend"] = "pass"
        result["interface"] = check_interface(design, n_inputs, n_outputs)
        if result["interface"]["status"] != "pass":
            result["status"] = "interface_fail"
            return result
        result["lowered_sha256"] = hashlib.sha256(lowered.read_bytes()).hexdigest()
        replay = bitparallel(truth_snapshot, design) if bitparallel is not None else {"status": "unsupported"}
        if replay.get("status") == "unsupported":
            result["bitparallel_fallback_reason"] = replay.get("reason", "Bit-parallel checker unavailable")
            replay = run_one(truth_snapshot, lowered, "x", "y", compile_timeout, run_timeout, workers=effective_workers)
            result["interleaved_replay"] = replay
        elif replay.get("status") not in ("pass", "mismatch"):
            return {**result, "status": "bitparallel_checker_error", "error": str(replay)}
        for key in ("n_inputs", "n_outputs", "vectors", "index", "got", "expected", "error", "detail", "verification_method"):
            if key in replay:
                result[key] = replay[key]
        result["status"] = replay["status"]
        if result["status"] == "pass" and (
            result.get("n_inputs") != n_inputs or result.get("n_outputs") != n_outputs
            or result.get("vectors") != 1 << n_inputs
        ):
            return {**result, "status": "incomplete_replay"}
        if truth.read_bytes() != truth_bytes or candidate.read_bytes() != candidate_bytes:
            result["status"] = "input_changed"
            return result
        if manifest is not None and result["status"] == "pass":
            try:
                current = cache.identity(truth_bytes, candidate_bytes, tools, sources,
                                         (frontend_timeout, compile_timeout, run_timeout),
                                         {"use_bitparallel": use_bitparallel, "replay_workers": effective_workers})
            except OSError:
                current = None
            if current != manifest:
                result["status"] = "verification_context_changed"
                return result
            result["cache"] = "stored" if cache.store(cache_root, manifest, result, lowered.read_bytes()) else "store_unavailable"
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", type=Path)
    parser.add_argument("verilog", type=Path)
    parser.add_argument("--yosys", type=Path, default=default_yosys())
    parser.add_argument("--frontend-timeout", type=int, default=120)
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cache-dir", type=Path, help="Trusted local complete-verification cache directory")
    parser.add_argument("--no-cache", action="store_true", help="Always run the frontend and full replay independently")
    parser.add_argument("--no-bitparallel", action="store_true", help="Use exhaustive Verilog replay even for supported Boolean cells")
    parser.add_argument("--replay-workers", type=int, help="1–4 exhaustive replay workers; small domains default to one")
    args = parser.parse_args()
    result = verify(
        args.truth,
        args.verilog,
        args.yosys,
        frontend_timeout=args.frontend_timeout,
        compile_timeout=args.compile_timeout,
        run_timeout=args.run_timeout,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
        use_bitparallel=not args.no_bitparallel,
        replay_workers=args.replay_workers,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status'].upper()} {result['verilog']}")
        if result.get("error"):
            print(result["error"])
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

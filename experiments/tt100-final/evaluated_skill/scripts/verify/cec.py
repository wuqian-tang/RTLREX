#!/usr/bin/env python3
"""Run combinational equivalence checking for two Verilog files.

The script first lowers each Verilog file with Yosys, then asks ABC to compare
the two lowered networks. AIGER is the default intermediate format because it
works with cec, dcec, and &cec.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


ROOT = Path.cwd().resolve()
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOOL_CONFIG = PACKAGE_ROOT / "tool_paths.env"
POW_CONST_MAP = PACKAGE_ROOT / "synthesis" / "yosys_pow_const_map.v"


@dataclass
class ToolResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class CecResult:
    case: str
    reference: str
    implementation: str
    engine: str
    abc_args: str
    status: str
    equivalent: Optional[bool]
    abc_output: str
    error: str


@dataclass
class SimResult:
    status: str
    vectors: int
    output: str
    error: str


@dataclass(frozen=True)
class PortContract:
    """Source-level top-port contract retained before logic lowering."""

    name: str
    direction: str
    left: int
    right: int
    signed: bool

    @property
    def width(self) -> int:
        return abs(self.left - self.right) + 1


def stop_process_group(proc: subprocess.Popen[str], grace: float = 2.0) -> Tuple[str, str]:
    """Terminate a tool and every child it spawned, then collect its output."""
    # Nested checkers can start new sessions for their own Yosys/ABC calls.
    # Retain their PIDs before killing the parent, while ancestry is observable.
    descendants = {proc.pid}
    parents = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, IndexError, ValueError):
            continue
    while True:
        more = {pid for pid, parent in parents.items() if parent in descendants}
        if more <= descendants:
            break
        descendants.update(more)
    def terminate(sig):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        for pid in descendants - {proc.pid}:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
    terminate(signal.SIGTERM)
    try:
        output = proc.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        terminate(signal.SIGKILL)
        output = proc.communicate()
    terminate(signal.SIGKILL)
    return output


def run_command(cmd: Sequence[str], timeout: int) -> ToolResult:
    cmd_list = list(cmd)
    try:
        proc = subprocess.Popen(
            cmd_list,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return ToolResult(cmd_list, 127, "", str(exc))
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return ToolResult(cmd_list, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        stdout, stderr = stop_process_group(proc)
        return ToolResult(cmd_list, 124, stdout, stderr + f"\nTimeout after {timeout}s")


def stop_process(proc: subprocess.Popen[str], grace: float = 2.0) -> Tuple[str, str]:
    return stop_process_group(proc, grace)


def run_cancellable_command(cmd: Sequence[str], timeout: int, cancel_event: threading.Event) -> ToolResult:
    cmd_list = list(cmd)
    if cancel_event.is_set():
        return ToolResult(cmd_list, 130, "", "Cancelled before start")
    try:
        proc = subprocess.Popen(
            cmd_list,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return ToolResult(cmd_list, 127, "", str(exc))

    deadline = time.monotonic() + timeout
    while True:
        if cancel_event.is_set():
            stdout, stderr = stop_process(proc)
            return ToolResult(cmd_list, 130, stdout, stderr + "\nCancelled")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stdout, stderr = stop_process(proc)
            return ToolResult(cmd_list, 124, stdout, stderr + f"\nTimeout after {timeout}s")

        try:
            stdout, stderr = proc.communicate(timeout=min(0.2, remaining))
            return ToolResult(cmd_list, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def yosys_script(verilog: Path, out_path: Path, out_format: str) -> str:
    audit_path = out_path.with_suffix(out_path.suffix + ".two_state.json")
    base = (
        f"read_verilog -sv {verilog}; "
        "hierarchy -check -top top; "
        # Record dependency cones before don't-care optimization or AIG export
        # can replace X/Z by a convenient Boolean constant.
        f"proc -noopt; flatten; write_json {audit_path}; "
        "opt; memory; opt; techmap; opt; "
    )
    if POW_CONST_MAP.exists():
        base += f"techmap -autoproc -map {POW_CONST_MAP}; opt; techmap; opt; "
    if out_format == "aiger":
        return base + f"aigmap; opt_clean; write_aiger -no-sort -symbols {out_path}"
    if out_format == "blif":
        return base + f"opt_clean; write_blif {out_path}"
    raise ValueError(f"unsupported output format: {out_format}")


def audit_two_state_output_cones(path: Path) -> Dict[str, int]:
    """Reject undefined values in complete output fan-in before Boolean export.

    Dead logic is outside this check. A reachable memory/stateful cell is
    unsupported: its initialization and transition semantics require a separate
    proof contract. This is a conservative two-state combinational guard, not
    four-state equivalence or a claim about whether a masked X affects a value.
    """
    design = json.loads(path.read_text())["modules"]["top"]
    ports, cells = design["ports"], design.get("cells", {})
    primary = {bit for port in ports.values() if port["direction"] == "input"
               for bit in port["bits"] if isinstance(bit, int)}
    drivers: Dict[int, List[str]] = {}
    for name, cell in cells.items():
        for port, direction in cell.get("port_directions", {}).items():
            if direction == "output":
                for bit in cell["connections"][port]:
                    if isinstance(bit, int):
                        drivers.setdefault(bit, []).append(name)
    pending = [bit for port in ports.values() if port["direction"] == "output"
               for bit in port["bits"]]
    if not pending:
        raise ValueError("two-state audit: no output bits")
    output_bits, seen_bits, seen_cells = len(pending), set(), set()
    while pending:
        bit = pending.pop()
        if bit in ("0", "1"):
            continue
        if not isinstance(bit, int):
            raise ValueError(f"two-state audit: X/Z or unsupported constant {bit!r} in output fan-in")
        if bit in seen_bits:
            continue
        seen_bits.add(bit)
        if bit in primary:
            if bit in drivers:
                raise ValueError("two-state audit: driven primary input in output fan-in")
            continue
        source = drivers.get(bit, [])
        if len(source) != 1:
            raise ValueError(f"two-state audit: undriven or multiply driven output-cone bit {bit}")
        name = source[0]
        if name in seen_cells:
            continue
        seen_cells.add(name)
        cell = cells[name]
        kind = cell["type"].lower()
        if any(token in kind for token in ("mem", "dff", "latch", "sr_")):
            raise ValueError(f"two-state audit: unsupported state/memory cell {cell['type']}")
        for port, direction in cell.get("port_directions", {}).items():
            if direction == "input":
                pending.extend(cell["connections"][port])
    return {"output_bits": output_bits, "reachable_bits": len(seen_bits),
            "reachable_cells": len(seen_cells)}


def lower_with_yosys(yosys: Path, verilog: Path, out_path: Path, out_format: str, timeout: int) -> ToolResult:
    result = run_command([str(yosys), "-q", "-p", yosys_script(verilog, out_path, out_format)], timeout)
    if result.returncode:
        return result
    try:
        audit = audit_two_state_output_cones(out_path.with_suffix(out_path.suffix + ".two_state.json"))
        out_path.with_suffix(out_path.suffix + ".two_state_audit.json").write_text(json.dumps({"status": "pass", **audit}, sort_keys=True) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ToolResult(result.command, 1, result.stdout, result.stderr + "\n" + str(exc))
    return result


def aiger_io_symbols(path: Path) -> Tuple[List[str], List[str]]:
    """Read complete symbols from a plain combinational binary AIGER file."""
    data = path.read_bytes()
    newline = data.index(b"\n")
    header = data[:newline].split()
    if header[0] != b"aig" or len(header) < 6 or len(header) > 10:
        raise ValueError("expected binary AIGER")
    numbers = [int(x) for x in header[1:]]
    maximum, inputs, latches, outputs, gates = numbers[:5]
    if latches or any(numbers[5:]) or maximum != inputs + gates:
        raise ValueError("AIGER state/formal properties or noncanonical variable count")
    pos = newline + 1
    for _ in range(outputs):
        end = data.index(b"\n", pos)
        literal = int(data[pos:end])
        if not 0 <= literal <= 2 * maximum + 1:
            raise ValueError("AIGER output literal out of range")
        pos = end + 1
    # Skip the two unsigned delta-varints of each AND gate. Do not search
    # binary gate bytes for a text marker: those bytes can resemble symbols.
    for _ in range(2 * gates):
        length = 0
        while True:
            value = data[pos]
            pos += 1
            length += 1
            if length > 10:
                raise ValueError("invalid AIGER delta-varint")
            if value < 128:
                break
    symbols = {"i": {}, "o": {}}
    for line in data[pos:].decode("utf-8").splitlines():
        if line == "c":
            break
        match = re.fullmatch(r"([io])(\d+) ([^\s]+)", line)
        if not match:
            raise ValueError("missing, aliased, or unsupported AIGER I/O symbol")
        kind, index, name = match.group(1), int(match.group(2)), match.group(3)
        if index in symbols[kind]:
            raise ValueError("duplicate AIGER I/O index")
        symbols[kind][index] = name
    result = []
    for kind, size in (("i", inputs), ("o", outputs)):
        if set(symbols[kind]) != set(range(size)):
            raise ValueError("incomplete AIGER I/O symbols")
        ordered = [symbols[kind][i] for i in range(size)]
        if len(set(ordered)) != size:
            raise ValueError("duplicate AIGER I/O names")
        result.append(ordered)
    return result[0], result[1]


def audit_aiger_pair(reference: Path, ref_aig: Path, impl_aig: Path) -> None:
    ref_io, impl_io = aiger_io_symbols(ref_aig), aiger_io_symbols(impl_aig)
    if ref_io != impl_io:
        raise ValueError("serialized AIGER input/output bit order differs")
    contract = parse_top_port_contract(reference)
    for direction, actual in zip(("input", "output"), ref_io):
        # Yosys AIGER symbols use zero-based offsets within each packed port,
        # independently of its source range orientation/start offset.
        expected = {p.name if p.width == 1 else f"{p.name}[{i}]"
                    for p in contract if p.direction == direction for i in range(p.width)}
        if set(actual) != expected:
            raise ValueError(f"AIGER {direction} bit coverage differs from source interface")


def parse_abc_equivalence(output: str, returncode: int) -> Tuple[str, Optional[bool], str]:
    lowered = output.lower()
    # A watchdog timeout or abnormal exit dominates any partial success text
    # already flushed by a child process.
    if returncode == 124 or "timeout" in lowered:
        return "timeout", None, output.strip()
    if returncode != 0:
        return "error", None, output.strip()
    if "undecided" in lowered:
        return "unknown", None, output.strip()
    if "networks are not equivalent" in lowered or "not equivalent" in lowered:
        return "fail", False, ""
    if "networks are equivalent" in lowered or "equivalent after structural hashing" in lowered:
        return "pass", True, ""
    return "unknown", None, output.strip()


def parse_smtbmc_equivalence(output: str, returncode: int) -> Tuple[str, Optional[bool], str]:
    lowered = output.lower()
    if returncode == 124 or "timeout after" in lowered:
        return "timeout", None, output.strip()
    # A conclusive counterexample is not a promoted success and some smtbmc
    # versions report it with a nonzero exit status.
    if "status: failed" in lowered or "assert failed" in lowered:
        return "fail", False, output.strip()
    if returncode != 0:
        return "error", None, output.strip()
    if "status: passed" in lowered:
        return "pass", True, ""
    return "unknown", None, output.strip()


def strip_verilog_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def split_comma_list(text: str) -> List[str]:
    pieces: List[str] = []
    start = 0
    depth = 0
    for idx, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            pieces.append(text[start:idx].strip())
            start = idx + 1
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces


def top_module_text(text: str) -> str:
    """Isolate top so helper module/function ports cannot alter its contract."""
    cleaned = strip_verilog_comments(text)
    starts = list(re.finditer(r"\bmodule\s+top\b", cleaned))
    if len(starts) != 1:
        raise ValueError("expected exactly one module top")
    start = starts[0].start()
    end = re.search(r"\bendmodule\b", cleaned[start:])
    if end is None:
        raise ValueError("module top has no endmodule")
    top = cleaned[start:start + end.end()]
    # Function/task arguments have module-local syntax, but are not top ports.
    return re.sub(r"\b(function|task)\b.*?\bend\1\b", "", top, flags=re.S)


def parse_module_ports(text: str) -> List[str]:
    cleaned = strip_verilog_comments(text)
    match = re.search(r"\bmodule\s+top\s*\((.*?)\)\s*;", cleaned, flags=re.S)
    if not match:
        raise ValueError("module top port list not found")
    ports: List[str] = []
    for raw in split_comma_list(match.group(1)):
        name = raw.strip()
        name = re.sub(r"\b(input|output|inout|wire|reg|logic|signed|unsigned)\b", " ", name)
        name = re.sub(r"\[[^\]]+\]", " ", name)
        name = name.split("=")[0].strip()
        port_match = re.search(r"([A-Za-z_][A-Za-z0-9_$]*)", name)
        if port_match:
            ports.append(port_match.group(1))
    return ports


def parse_range_width(range_text: Optional[str]) -> int:
    if not range_text:
        return 1
    match = re.fullmatch(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", range_text.strip())
    if not match:
        raise ValueError(f"unsupported port range: {range_text}")
    left = int(match.group(1))
    right = int(match.group(2))
    return abs(left - right) + 1


def parse_range_contract(range_text: Optional[str]) -> Tuple[int, int]:
    if not range_text:
        return 0, 0
    match = re.fullmatch(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", range_text.strip())
    if not match:
        raise ValueError(f"unsupported port range: {range_text}")
    return int(match.group(1)), int(match.group(2))


def parse_top_port_contract(path: Path) -> List[PortContract]:
    """Parse ordered direction/range/signedness for the source-level top ports.

    The supported contract intentionally fails closed on symbolic packed ranges,
    escaped identifiers, missing declarations, and inout ports.
    """

    cleaned = top_module_text(path.read_text())
    module_match = re.search(r"\bmodule\s+top\s*\((.*?)\)\s*;", cleaned, flags=re.S)
    if not module_match:
        raise ValueError("module top port list not found")
    ordered_names = parse_module_ports(cleaned)
    if not ordered_names:
        raise ValueError("module top has no parseable ports")

    by_name: Dict[str, PortContract] = {}
    current_direction: Optional[str] = None
    current_left, current_right = 0, 0
    current_signed = False
    for raw_port in split_comma_list(module_match.group(1)):
        declaration = raw_port.strip()
        direction_match = re.match(r"\b(input|output|inout)\b\s*(.*)", declaration, flags=re.S)
        if direction_match:
            current_direction = direction_match.group(1)
            if current_direction == "inout":
                raise ValueError("inout top ports are unsupported")
            declaration = direction_match.group(2)
            current_signed = bool(re.search(r"\bsigned\b", declaration))
            if len(re.findall(r"\[[^\]]+\]", declaration)) > 1:
                raise ValueError("multidimensional top ports are unsupported")
            range_match = re.search(r"\[[^\]]+\]", declaration)
            current_left, current_right = parse_range_contract(
                range_match.group(0) if range_match else None
            )
        if current_direction not in {"input", "output"}:
            continue
        declaration = re.sub(r"\[[^\]]+\]", " ", declaration)
        declaration = re.sub(r"\b(wire|reg|logic|signed|unsigned)\b", " ", declaration)
        declaration = declaration.split("=", 1)[0].strip()
        name_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_$]*)", declaration)
        if name_match:
            name = name_match.group(1)
            by_name[name] = PortContract(
                name, current_direction, current_left, current_right, current_signed
            )

    # Non-ANSI declarations appear after the module header.
    body = cleaned[module_match.end() :]
    for declaration_match in re.finditer(
        r"\b(input|output|inout)\b\s*([^;]+);", body, flags=re.S
    ):
        direction = declaration_match.group(1)
        if direction == "inout":
            raise ValueError("inout top ports are unsupported")
        declaration = declaration_match.group(2)
        signed = bool(re.search(r"\bsigned\b", declaration))
        if len(re.findall(r"\[[^\]]+\]", declaration)) > 1:
            raise ValueError("multidimensional top ports are unsupported")
        range_match = re.search(r"\[[^\]]+\]", declaration)
        left, right = parse_range_contract(range_match.group(0) if range_match else None)
        declaration = re.sub(r"\[[^\]]+\]", " ", declaration)
        declaration = re.sub(r"\b(wire|reg|logic|signed|unsigned)\b", " ", declaration)
        for raw_name in split_comma_list(declaration):
            name = raw_name.split("=", 1)[0].strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
                raise ValueError(f"unsupported top-port declaration: {raw_name}")
            by_name[name] = PortContract(name, direction, left, right, signed)

    missing = [name for name in ordered_names if name not in by_name]
    extra = [name for name in by_name if name not in ordered_names]
    if missing or extra:
        raise ValueError(f"incomplete top-port contract: missing={missing}, extra={extra}")
    return [by_name[name] for name in ordered_names]


def compare_top_port_contracts(reference: Path, implementation: Path) -> Tuple[bool, str]:
    reference_contract = parse_top_port_contract(reference)
    implementation_contract = parse_top_port_contract(implementation)
    if reference_contract == implementation_contract:
        return True, ""
    return (
        False,
        "top interfaces do not match: "
        f"reference={reference_contract!r}; implementation={implementation_contract!r}",
    )


def parse_port_declarations(text: str) -> Tuple[Dict[str, int], Dict[str, int]]:
    cleaned = strip_verilog_comments(text)
    inputs: Dict[str, int] = {}
    outputs: Dict[str, int] = {}
    module_match = re.search(r"\bmodule\s+top\s*\((.*?)\)\s*;", cleaned, flags=re.S)
    if module_match:
        current_direction: Optional[str] = None
        current_width = 1
        for raw_port in split_comma_list(module_match.group(1)):
            declaration = raw_port.strip()
            direction_match = re.match(r"\b(input|output)\b\s*(.*)", declaration, flags=re.S)
            if direction_match:
                current_direction = direction_match.group(1)
                declaration = direction_match.group(2)
                current_width = 1
            if current_direction not in {"input", "output"}:
                continue
            range_match = re.search(r"\[[^\]]+\]", declaration)
            if range_match:
                current_width = parse_range_width(range_match.group(0))
            declaration = re.sub(r"\[[^\]]+\]", " ", declaration)
            declaration = re.sub(r"\b(wire|reg|logic|signed|unsigned)\b", " ", declaration)
            declaration = declaration.split("=")[0].strip()
            name_match = re.match(r"([A-Za-z_][A-Za-z0-9_$]*)", declaration)
            if name_match:
                target = inputs if current_direction == "input" else outputs
                target[name_match.group(1)] = current_width
    # Verilog permits packed ranges to touch the direction keyword, for
    # example ``input[31:0] in1;``.  Accept both that form and conventional
    # whitespace-separated declarations.
    for match in re.finditer(r"\b(input|output)\b\s*([^;]+);", cleaned, flags=re.S):
        direction = match.group(1)
        declaration = match.group(2)
        range_match = re.search(r"\[[^\]]+\]", declaration)
        width = parse_range_width(range_match.group(0) if range_match else None)
        declaration = re.sub(r"\[[^\]]+\]", " ", declaration)
        declaration = re.sub(r"\b(wire|reg|logic|signed|unsigned)\b", " ", declaration)
        target = inputs if direction == "input" else outputs
        for raw_name in split_comma_list(declaration):
            raw_name = raw_name.split("=")[0].strip()
            name_match = re.match(r"([A-Za-z_][A-Za-z0-9_$]*)", raw_name)
            if name_match:
                target[name_match.group(1)] = width
    return inputs, outputs


def parse_top_interface(path: Path) -> Tuple[List[Tuple[str, int]], List[Tuple[str, int]]]:
    contract = parse_top_port_contract(path)
    inputs = [(port.name, port.width) for port in contract if port.direction == "input"]
    outputs = [(port.name, port.width) for port in contract if port.direction == "output"]
    if not inputs or not outputs:
        raise ValueError(f"could not parse top inputs/outputs from {path}")
    return inputs, outputs


def audit_yosys_port_contracts(model: dict, reference: Path, implementation: Path) -> None:
    """Cross-check source parsing against Yosys before miter optimization."""
    for module_name, source in (("gold", reference), ("gate", implementation)):
        expected = parse_top_port_contract(source)
        serialized = model["modules"][module_name]["ports"]
        if list(serialized) != [p.name for p in expected]:
            raise ValueError(f"{module_name}: serialized port names/order differ")
        for p in expected:
            q = serialized[p.name]
            if (q["direction"] != p.direction or len(q["bits"]) != p.width
                    or int(q.get("offset", 0)) != min(p.left, p.right)
                    or bool(q.get("upto", 0)) != (p.left < p.right)
                    or bool(q.get("signed", 0)) != p.signed):
                raise ValueError(f"{module_name}.{p.name}: serialized direction/range/signedness differs")


def rename_top_module(text: str, module_name: str) -> str:
    return re.sub(r"\bmodule\s+top\s*\(", f"module {module_name}(", text, count=1)


def hex_digits(width: int) -> int:
    return max(1, (width + 3) // 4)


def random_vectors(inputs: Sequence[Tuple[str, int]], count: int, seed: int) -> List[Dict[str, int]]:
    vectors: List[Dict[str, int]] = []
    vectors.append({name: 0 for name, _width in inputs})
    vectors.append({name: (1 << width) - 1 for name, width in inputs})
    rng = random.Random(seed)
    while len(vectors) < count:
        vectors.append({name: rng.randrange(1 << width) for name, width in inputs})
    return vectors[:count]


def build_random_sim_testbench(
    inputs: Sequence[Tuple[str, int]],
    outputs: Sequence[Tuple[str, int]],
    vectors: Sequence[Dict[str, int]],
) -> str:
    lines = ["module tb;"]
    for name, width in inputs:
        lines.append(f"  reg [{width - 1}:0] {name};" if width > 1 else f"  reg {name};")
    for name, width in outputs:
        lines.append(f"  wire [{width - 1}:0] ref_{name}, impl_{name};" if width > 1 else f"  wire ref_{name}, impl_{name};")
    input_conns = [f".{name}({name})" for name, _width in inputs]
    ref_conns = ", ".join(input_conns + [f".{name}(ref_{name})" for name, _width in outputs])
    impl_conns = ", ".join(input_conns + [f".{name}(impl_{name})" for name, _width in outputs])
    lines.append(f"  ref_top ref_dut({ref_conns});")
    lines.append(f"  impl_top impl_dut({impl_conns});")
    lines.append("  initial begin")
    for idx, vector in enumerate(vectors):
        for name, width in inputs:
            lines.append(f"    {name} = {width}'h{vector[name]:0{hex_digits(width)}x};")
        lines.append("    #1;")
        mismatch_expr = " || ".join(f"ref_{name} !== impl_{name}" for name, _width in outputs)
        lines.append(f"    if ({mismatch_expr}) begin")
        lines.append(f"      $display(\"MISMATCH vector={idx}\");")
        for name, _width in outputs:
            lines.append(f"      $display(\"  {name} ref=%h impl=%h\", ref_{name}, impl_{name});")
        lines.append("      $finish;")
        lines.append("    end")
    lines.append(f"    $display(\"PASS random_sim_vectors={len(vectors)}\");")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def run_random_sim_check(
    reference: Path,
    implementation: Path,
    vector_count: int,
    seed: int,
    compile_timeout: int,
    run_timeout: int,
) -> SimResult:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iverilog or not vvp:
        return SimResult("error", 0, "", "iverilog or vvp not found")
    try:
        inputs, outputs = parse_top_interface(reference)
        impl_inputs, impl_outputs = parse_top_interface(implementation)
    except (OSError, ValueError) as exc:
        return SimResult("error", 0, "", str(exc))
    if inputs != impl_inputs or outputs != impl_outputs:
        return SimResult("error", 0, "", "top interfaces do not match")

    vectors = random_vectors(inputs, vector_count, seed)
    try:
        with tempfile.TemporaryDirectory(prefix="cec_random_sim_") as tmp:
            tmpdir = Path(tmp)
            ref_v = tmpdir / "ref.v"
            impl_v = tmpdir / "impl.v"
            tb_v = tmpdir / "tb.v"
            simv = tmpdir / "simv"
            ref_v.write_text(rename_top_module(reference.read_text(), "ref_top"))
            impl_v.write_text(rename_top_module(implementation.read_text(), "impl_top"))
            tb_v.write_text(build_random_sim_testbench(inputs, outputs, vectors))

            compile_proc = subprocess.run(
                [iverilog, "-g2012", "-o", str(simv), str(ref_v), str(impl_v), str(tb_v)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=compile_timeout,
                check=False,
            )
            if compile_proc.returncode != 0:
                return SimResult("error", len(vectors), compile_proc.stdout, compile_proc.stderr.strip())

            run_proc = subprocess.run(
                [vvp, str(simv)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=run_timeout,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
        return SimResult("error", len(vectors), stdout, stderr + "random simulation timeout")

    output = run_proc.stdout + run_proc.stderr
    if run_proc.returncode != 0:
        return SimResult("error", len(vectors), output, "random simulation failed")
    if "MISMATCH" in output:
        return SimResult("fail", len(vectors), output.strip(), "")
    if "PASS random_sim_vectors=" in output:
        return SimResult("pass", len(vectors), output.strip(), "")
    return SimResult("error", len(vectors), output.strip(), "random simulation did not report a result")


def normalize_engine(engine: str) -> str:
    return "&cec" if engine == "acec" else engine


def load_tool_config(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def configured_tool(name: str, explicit: Optional[str], config: Dict[str, str], config_path: Path) -> str:
    if explicit:
        return explicit
    if name in config and config[name]:
        return config[name]
    raise SystemExit(
        f"{name} is not configured. Run ./install_skill.sh to generate {config_path}, "
        f"or pass --{name.lower()} <path>."
    )


def resolve_executable(value: str, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or len(candidate.parts) > 1:
        if candidate.exists():
            return candidate
        raise SystemExit(f"{label} executable not found: {value}")
    found = shutil.which(value)
    if found:
        return Path(found)
    raise SystemExit(f"{label} executable not found in PATH or configured path: {value}")


def resolve_optional_smtbmc(explicit: Optional[str], config: Dict[str, str], yosys: Path) -> Path:
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    if config.get("YOSYS_SMTBMC"):
        candidates.append(config["YOSYS_SMTBMC"])
    candidates.extend(
        [
            "yosys-smtbmc",
            str(yosys.parent / "yosys-smtbmc"),
            str(ROOT / "external" / "yosys" / "yosys-smtbmc"),
        ]
    )
    errors: List[str] = []
    for candidate in candidates:
        try:
            return resolve_executable(candidate, "yosys-smtbmc")
        except SystemExit as exc:
            errors.append(str(exc))
    raise SystemExit("yosys-smtbmc executable not found. Tried: " + ", ".join(candidates) + "\n" + "\n".join(errors[-3:]))


def verilog_port_decl(direction: str, name: str, width: int) -> str:
    if width == 1:
        return f"  {direction} {name};"
    return f"  {direction} [{width - 1}:0] {name};"


def verilog_wire_pair(prefix_a: str, prefix_b: str, name: str, width: int) -> str:
    if width == 1:
        return f"  wire {prefix_a}_{name}, {prefix_b}_{name};"
    return f"  wire [{width - 1}:0] {prefix_a}_{name}, {prefix_b}_{name};"


def build_assert_miter(inputs: Sequence[Tuple[str, int]], outputs: Sequence[Tuple[str, int]]) -> str:
    ports = ", ".join(name for name, _width in inputs)
    lines = [f"module miter({ports});"]
    for name, width in inputs:
        lines.append(verilog_port_decl("input", name, width))
    for name, width in outputs:
        lines.append(verilog_wire_pair("gold", "gate", name, width))
    input_conns = [f".{name}({name})" for name, _width in inputs]
    gold_conns = ", ".join(input_conns + [f".{name}(gold_{name})" for name, _width in outputs])
    gate_conns = ", ".join(input_conns + [f".{name}(gate_{name})" for name, _width in outputs])
    lines.append(f"  gold u_gold({gold_conns});")
    lines.append(f"  gate u_gate({gate_conns});")
    comparisons = " && ".join(
        f"(gold_{name} == gate_{name})" for name, _width in outputs
    )
    lines.append("  wire outputs_equal;")
    lines.append(f"  assign outputs_equal = {comparisons};")
    lines.append("  always @* begin")
    # Keep the comparison in ordinary procedural control flow. Some Yosys
    # versions otherwise infer an empty @* sensitivity list for a block that
    # contains only immediate assertions, silently dropping the proof duty.
    lines.append("    if (!outputs_equal)")
    lines.append("      assert(1'b0);")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def audit_smt2_proof_duty(
    smt2_text: str, outputs: Sequence[Tuple[str, int]]
) -> Tuple[bool, str]:
    """Check that every miter output comparison reaches a serialized assertion.

    This is intentionally tied to the simple miter emitted above and to Yosys'
    documented SMT2 comments.  If that representation changes, fail closed
    rather than accepting a solver result for an unaudited proof property.
    """
    lines = smt2_text.splitlines()

    def balanced_definition(prefix: str) -> str:
        """Return one complete SMT2 define-fun form, including continuations."""
        for start, line in enumerate(lines):
            if not line.startswith(prefix):
                continue
            block: List[str] = []
            depth = 0
            for part in lines[start:]:
                block.append(part)
                code = part.split(";", 1)[0]
                depth += code.count("(") - code.count(")")
                if depth == 0:
                    return "\n".join(block)
            return ""
        return ""

    def symbol_with_comment(comment: str) -> Optional[str]:
        suffix = f"; \\{comment}"
        for line in lines:
            if suffix not in line:
                continue
            match = re.match(r"\((?:declare|define)-fun \|(miter#\d+)\|", line)
            if match:
                return match.group(1)
        return None

    equality_symbols: List[str] = []
    missing: List[str] = []
    for name, _width in outputs:
        gold_symbol = symbol_with_comment(f"gold_{name}")
        gate_symbol = symbol_with_comment(f"gate_{name}")
        if gold_symbol is None or gate_symbol is None:
            missing.append(f"{name}:serialized_output")
            continue
        equality_symbol: Optional[str] = None
        for line in lines:
            if f"|{gold_symbol}| state" not in line or f"|{gate_symbol}| state" not in line:
                continue
            match = re.match(r"\(define-fun \|(miter#\d+)\|.*\(= ", line)
            if match:
                equality_symbol = match.group(1)
                break
        if equality_symbol is None:
            missing.append(f"{name}:equality")
        else:
            equality_symbols.append(equality_symbol)

    outputs_equal_symbol = symbol_with_comment("outputs_equal")
    if outputs_equal_symbol is None:
        missing.append("outputs_equal:symbol")

    # Yosys may serialize a conjunction of three or more output equalities as
    # a tree of intermediate Boolean definitions.  Audit graph reachability,
    # not only direct references in the root definition.
    dependency_graph: Dict[str, set[str]] = {}
    for line in lines:
        match = re.match(r"\(define-fun \|(miter#\d+)\|", line)
        if not match:
            continue
        symbol = match.group(1)
        definition = balanced_definition(f"(define-fun |{symbol}|")
        dependency_graph[symbol] = set(
            re.findall(r"\(\|(miter#\d+)\| state\)", definition)
        )

    reachable: set[str] = set()
    pending = [outputs_equal_symbol] if outputs_equal_symbol else []
    while pending:
        symbol = pending.pop()
        if symbol in reachable:
            continue
        reachable.add(symbol)
        pending.extend(dependency_graph.get(symbol, set()) - reachable)
    for equality_symbol in equality_symbols:
        if equality_symbol not in reachable:
            missing.append(f"outputs_equal:missing_{equality_symbol}")

    enable_symbol: Optional[str] = None
    if outputs_equal_symbol is not None:
        for line in lines:
            if "; $assert" not in line or "_EN" not in line:
                continue
            if f"|{outputs_equal_symbol}| state" not in line:
                continue
            match = re.match(r"\(define-fun \|(miter#\d+)\|", line)
            if match:
                enable_symbol = match.group(1)
                break
    if enable_symbol is None:
        missing.append("assert_enable:outputs_equal_dependency")

    assertion_markers = sum("; yosys-smt2-assert" in line for line in lines)
    if assertion_markers < 1:
        missing.append("serialized_assertion")
    assertion_definitions: List[Tuple[str, str]] = []
    for line in lines:
        match = re.match(r"\(define-fun \|(miter_a \d+)\|", line)
        if match:
            assertion_definitions.append((match.group(1), line))
    assertion_dependency = bool(
        enable_symbol
        and any(
            f"|{enable_symbol}| state" in line
            for _symbol, line in assertion_definitions
        )
    )
    if not assertion_dependency:
        missing.append("assertion:enable_dependency")
    if len(assertion_definitions) != assertion_markers:
        missing.append("assertion:marker_definition_count")

    aggregate_definition = balanced_definition("(define-fun |miter_a|")
    if not aggregate_definition:
        missing.append("assertion:aggregate")
    for assertion_symbol, _line in assertion_definitions:
        if f"|{assertion_symbol}| state" not in aggregate_definition:
            missing.append(f"assertion:aggregate_missing_{assertion_symbol}")

    ok = not missing and len(equality_symbols) == len(outputs)
    detail = (
        f"proof_duty={'pass' if ok else 'fail'} outputs={len(outputs)} "
        f"output_equalities={len(equality_symbols)} assertions={assertion_markers}"
    )
    if missing:
        detail += " missing=" + ",".join(missing)
    return ok, detail


def abc_command(engine: str, abc_args: str, reference: Path, implementation: Path) -> str:
    engine = normalize_engine(engine)
    args = abc_args.strip()
    pieces = [engine]
    if args:
        pieces.append(args)
    pieces.extend([str(reference), str(implementation)])
    return " ".join(pieces)


def engine_attempts(engine: str, abc_extra: str) -> List[Tuple[str, str]]:
    engine = normalize_engine(engine)
    if engine != "auto":
        return [(engine, abc_extra)]
    if abc_extra:
        return [("&cec", abc_extra), ("dcec", abc_extra), ("cec", abc_extra)]
    return [
        ("&cec", ""),
        ("dcec", ""),
        ("cec", ""),
    ]


def format_attempt_log(result: CecResult) -> str:
    detail = result.abc_output.strip() or result.error.strip()
    return f"[{result.engine} {result.abc_args}] {result.status}\n{detail}"


def run_abc_attempt(
    case: str,
    reference: Path,
    implementation: Path,
    abc: Path,
    attempt_engine: str,
    attempt_args: str,
    abc_timeout: int,
    cancel_event: Optional[threading.Event] = None,
    result_reference: Optional[Path] = None,
    result_implementation: Optional[Path] = None,
) -> CecResult:
    result_reference = result_reference or reference
    result_implementation = result_implementation or implementation
    command = abc_command(attempt_engine, attempt_args, reference, implementation)
    if cancel_event is None:
        abc_result = run_command([str(abc), "-c", command], abc_timeout)
    else:
        abc_result = run_cancellable_command([str(abc), "-c", command], abc_timeout, cancel_event)
    abc_output = abc_result.stdout + abc_result.stderr
    if abc_result.returncode == 130 and "cancelled" in abc_output.lower():
        return CecResult(
            case,
            str(result_reference),
            str(result_implementation),
            attempt_engine,
            attempt_args,
            "cancelled",
            None,
            abc_output,
            "ABC attempt cancelled",
        )
    status, equivalent, error = parse_abc_equivalence(abc_output, abc_result.returncode)
    return CecResult(
        case,
        str(result_reference),
        str(result_implementation),
        attempt_engine,
        attempt_args,
        status,
        equivalent,
        abc_output,
        error,
    )


def combine_auto_results(
    case: str,
    reference: Path,
    implementation: Path,
    abc_extra: str,
    results: Sequence[CecResult],
) -> CecResult:
    attempt_log = "\n\n".join(format_attempt_log(result) for result in results)
    combined_output = "\n\n".join(result.abc_output.strip() for result in results if result.abc_output.strip())
    passes = [result for result in results if result.status == "pass"]
    failures = [result for result in results if result.status == "fail"]
    if passes and failures:
        return CecResult(
            case,
            str(reference),
            str(implementation),
            "auto",
            abc_extra,
            "conflict",
            None,
            combined_output,
            "ABC engines returned contradictory conclusive statuses.\n\n" + attempt_log,
        )
    if failures:
        selected = failures[0]
        return CecResult(
            case,
            str(reference),
            str(implementation),
            selected.engine,
            selected.abc_args,
            "fail",
            False,
            combined_output,
            attempt_log,
        )
    if passes:
        selected = passes[0]
        return CecResult(
            case,
            str(reference),
            str(implementation),
            selected.engine,
            selected.abc_args,
            "pass",
            True,
            combined_output,
            attempt_log,
        )
    if results and all(result.status in {"timeout", "unknown"} for result in results):
        return CecResult(
            case,
            str(reference),
            str(implementation),
            "auto",
            abc_extra,
            "unknown",
            None,
            combined_output,
            attempt_log,
        )
    return CecResult(
        case,
        str(reference),
        str(implementation),
        "auto",
        abc_extra,
        "error",
        None,
        combined_output,
        attempt_log,
    )


def run_auto_abc_attempts(
    case: str,
    reference: Path,
    implementation: Path,
    abc: Path,
    abc_extra: str,
    abc_timeout: int,
    result_reference: Path,
    result_implementation: Path,
) -> CecResult:
    attempts = engine_attempts("auto", abc_extra)
    results_by_attempt: Dict[Tuple[str, str], CecResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(attempts)) as executor:
        futures = {
            executor.submit(
                run_abc_attempt,
                case,
                reference,
                implementation,
                abc,
                attempt_engine,
                attempt_args,
                abc_timeout,
                None,
                result_reference,
                result_implementation,
            ): (attempt_engine, attempt_args)
            for attempt_engine, attempt_args in attempts
        }
        for future in concurrent.futures.as_completed(futures):
            attempt_engine, attempt_args = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - defensive guard for worker bugs.
                result = CecResult(
                    case,
                    str(result_reference),
                    str(result_implementation),
                    attempt_engine,
                    attempt_args,
                    "error",
                    None,
                    "",
                    f"{type(exc).__name__}: {exc}",
                )
            results_by_attempt[(attempt_engine, attempt_args)] = result
    results = [results_by_attempt[attempt] for attempt in attempts if attempt in results_by_attempt]
    return combine_auto_results(case, result_reference, result_implementation, abc_extra, results)


def run_smt_cec_pair(
    case: str,
    reference: Path,
    implementation: Path,
    yosys: Path,
    smtbmc: Path,
    solver: str,
    yosys_timeout: int,
    smt_timeout: int,
    tmp_root: Optional[Path],
    keep_tmp: bool,
) -> CecResult:
    if not reference.exists():
        return CecResult(case, str(reference), str(implementation), "smt", solver, "missing_ref", None, "", "reference file not found")
    if not implementation.exists():
        return CecResult(case, str(reference), str(implementation), "smt", solver, "missing_impl", None, "", "implementation file not found")
    try:
        inputs, outputs = parse_top_interface(reference)
        impl_inputs, impl_outputs = parse_top_interface(implementation)
    except (OSError, ValueError) as exc:
        return CecResult(case, str(reference), str(implementation), "smt", solver, "interface_error", None, "", str(exc))
    if inputs != impl_inputs or outputs != impl_outputs:
        return CecResult(case, str(reference), str(implementation), "smt", solver, "interface_mismatch", None, "", "top interfaces do not match")

    if tmp_root:
        tmp_root.mkdir(parents=True, exist_ok=True)
    tmpdir_ctx = None
    if keep_tmp:
        tmpdir_name = tempfile.mkdtemp(
            prefix=f"{case}_smt_",
            dir=tmp_root,
        )
    else:
        tmpdir_ctx = tempfile.TemporaryDirectory(
            prefix=f"{case}_smt_",
            dir=tmp_root,
        )
        tmpdir_name = tmpdir_ctx.name
    tmpdir = Path(tmpdir_name)
    try:
        ref_v = tmpdir / "gold.v"
        impl_v = tmpdir / "gate.v"
        miter_v = tmpdir / "miter.sv"
        smt2 = tmpdir / "miter.smt2"
        ref_v.write_text(rename_top_module(reference.read_text(), "gold"))
        impl_v.write_text(rename_top_module(implementation.read_text(), "gate"))
        miter_v.write_text(build_assert_miter(inputs, outputs))
        script = (
            f"read_verilog -formal -sv {ref_v}; "
            f"read_verilog -formal -sv {impl_v}; "
            f"read_verilog -formal -sv {miter_v}; "
            "hierarchy -check -top miter; proc; "
            f"write_json {tmpdir / 'interfaces.json'}; "
            "prep -top miter; "
            # Newer Yosys frontends represent immediate assertions as
            # generalized $check cells. write_smt2 ignores those unless they
            # are lowered to ordinary $assert cells first.
            "chformal -lower; "
            f"write_smt2 -wires {smt2}"
        )
        yosys_result = run_command([str(yosys), "-q", "-p", script], yosys_timeout)
        if yosys_result.returncode != 0:
            return CecResult(
                case,
                str(reference),
                str(implementation),
                "smt",
                solver,
                "smt_yosys_error",
                None,
                yosys_result.stdout + yosys_result.stderr,
                "Yosys failed while writing SMT2",
            )
        if not smt2.exists():
            return CecResult(
                case,
                str(reference),
                str(implementation),
                "smt",
                solver,
                "smt_proof_duty_error",
                None,
                yosys_result.stdout + yosys_result.stderr,
                "Yosys returned success without producing the SMT2 model",
            )
        try:
            audit_yosys_port_contracts(
                json.loads((tmpdir / "interfaces.json").read_text()), reference, implementation
            )
        except (OSError, ValueError, KeyError) as exc:
            return CecResult(case, str(reference), str(implementation), "smt", solver,
                             "smt_proof_duty_error", None, "", str(exc))
        smt2_text = smt2.read_text(errors="replace")
        proof_duty_ok, proof_duty_detail = audit_smt2_proof_duty(smt2_text, outputs)
        if not proof_duty_ok:
            return CecResult(
                case,
                str(reference),
                str(implementation),
                "smt",
                solver,
                "smt_proof_duty_error",
                None,
                yosys_result.stdout + yosys_result.stderr,
                proof_duty_detail,
            )
        smt_result = run_command([str(smtbmc), "-s", solver, "-t", "1", "-m", "miter", str(smt2)], smt_timeout)
        smt_output = smt_result.stdout + smt_result.stderr
        status, equivalent, error = parse_smtbmc_equivalence(smt_output, smt_result.returncode)
        bvmul_hits = smt2_text.count("bvmul")
        smt2_size = smt2.stat().st_size
        detail = (
            f"solver={solver} smt2={smt2_size} bytes bvmul={bvmul_hits} "
            f"{proof_duty_detail}"
        )
        if error:
            detail += f"\n{error}"
        return CecResult(
            case,
            str(reference),
            str(implementation),
            "smt",
            solver,
            status,
            equivalent,
            smt_output,
            detail,
        )
    finally:
        if keep_tmp:
            print(f"{case}: kept SMT temporary files in {tmpdir_name}", file=sys.stderr)
        elif tmpdir_ctx is not None:
            tmpdir_ctx.cleanup()


def apply_random_sim_fallback(
    result: CecResult,
    reference: Path,
    implementation: Path,
    sim_vectors: int,
    sim_seed: int,
    sim_compile_timeout: int,
    sim_run_timeout: int,
) -> CecResult:
    if result.status != "unknown":
        return result
    sim_result = run_random_sim_check(
        reference,
        implementation,
        sim_vectors,
        sim_seed,
        sim_compile_timeout,
        sim_run_timeout,
    )
    sim_detail = (
        f"random simulation fallback: status={sim_result.status}, "
        f"vectors={sim_result.vectors}, seed={sim_seed}"
    )
    if sim_result.output:
        sim_detail += f"\n{sim_result.output}"
    if sim_result.error:
        sim_detail += f"\n{sim_result.error}"

    previous_detail = result.error.strip()
    combined_error = f"{previous_detail}\n\n{sim_detail}".strip()
    combined_output = "\n\n".join(part for part in [result.abc_output.strip(), sim_result.output.strip()] if part)
    if sim_result.status == "pass":
        return CecResult(
            result.case,
            result.reference,
            result.implementation,
            result.engine,
            result.abc_args,
            "pass (non-strict)",
            True,
            combined_output,
            combined_error,
        )
    if sim_result.status == "fail":
        return CecResult(
            result.case,
            result.reference,
            result.implementation,
            result.engine,
            result.abc_args,
            "fail",
            False,
            combined_output,
            combined_error,
        )
    return CecResult(
        result.case,
        result.reference,
        result.implementation,
        result.engine,
        result.abc_args,
        "error",
        None,
        combined_output,
        combined_error,
    )


def run_algebraic_cec_pair(case, reference, implementation, yosys, total_timeout,
                           term_cap, tmp_root, keep_tmp, sliced_outputs=(),
                           case_split_bits=(), backend="algebraic", cone_input_cap=6, coefficient_inputs=(),
                           coefficient_engine="cec", bdd_node_cap=1000000, bdd_order="bit-major"):
    """Run the certificate-producing algebraic backend under one watchdog."""
    if tmp_root:
        tmp_root.mkdir(parents=True, exist_ok=True)
    context = None if keep_tmp else tempfile.TemporaryDirectory(prefix=f"{case}_algebraic_", dir=tmp_root)
    work = Path(tempfile.mkdtemp(prefix=f"{case}_algebraic_", dir=tmp_root) if keep_tmp else context.name).resolve()
    try:
        if coefficient_engine not in ("cec", "bdd") or bdd_node_cap < 2 or bdd_order not in ("bit-major", "port-major"):
            raise ValueError("invalid coefficient engine or BDD resource/order option")
        if backend != "algebraic-terminal" and (coefficient_engine != "cec" or bdd_node_cap != 1000000 or bdd_order != "bit-major"):
            raise ValueError("coefficient engine/BDD options require algebraic-terminal")
        if backend in ("algebraic-cones", "algebraic-terminal") and (sliced_outputs or case_split_bits):
            raise ValueError(f"{backend} checks all outputs with free inputs; slicing/case options are unsupported")
        module = {"algebraic-cones": "verify.small_pi_backend", "algebraic-terminal": "verify.algebraic_terminal"}.get(backend, "verify.algebraic")
        command = [sys.executable, "-c",
                   'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module(' + repr(module) + ',run_name="__main__")',
                   str(PACKAGE_ROOT), "--reference", str(reference.resolve()),
                   "--candidate", str(implementation.resolve()), "--out", str(work / "proof"),
                   "--yosys", str(yosys), "--term-cap", str(term_cap),
                   "--timeout", str(total_timeout)]
        if backend in ("algebraic-cones", "algebraic-terminal"):
            # This wrapper owns the complete process-group watchdog.
            command.extend(["--worker", "--cone-input-cap", str(cone_input_cap)])
        if backend == "algebraic-terminal":
            if not coefficient_inputs:
                raise ValueError("algebraic-terminal requires coefficient input ports")
            command.extend(["--coefficient-engine", coefficient_engine,
                            "--bdd-node-cap", str(bdd_node_cap), "--bdd-order", bdd_order])
            for name in coefficient_inputs:
                command.extend(["--coefficient-input", name])
        for output in sliced_outputs:
            command.extend(["--sliced-output", output])
        for bit in case_split_bits:
            command.extend(["--case-split-bit", bit])
        (work / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        result = run_command(command, total_timeout)
        output = result.stdout + result.stderr
        (work / "backend.log").write_text(output)
        status, equivalent, error = "unknown", None, ""
        if result.returncode == 124:
            status, error = "timeout", "Algebraic proof exceeded the total budget"
        elif result.returncode != 0:
            status, error = "error", "Algebraic backend exited abnormally; see backend.log"
        else:
            record = json.loads((work / "proof" / "result.json").read_text())
            if (record.get("status") == "pass" and record.get("equivalent") is True
                    and record.get("strict") is True and record.get("all_outputs_compared") is True):
                status, equivalent = "pass", True
            else:
                error = str(record.get("error", record.get("reason", "Algebraic proof is incomplete")))
        return CecResult(case, str(reference), str(implementation), backend, "",
                         status, equivalent, f"artifacts={work}\n" + output, error)
    except (OSError, ValueError, KeyError) as exc:
        return CecResult(case, str(reference), str(implementation), backend, "",
                         "error", None, "", str(exc))
    finally:
        if context:
            context.cleanup()


def run_cec_pair(
    case: str,
    reference: Path,
    implementation: Path,
    yosys: Path,
    abc: Path,
    smtbmc: Optional[Path],
    engine: str,
    abc_extra: str,
    smt_solver: str,
    smt_timeout: int,
    smt_fallback: bool,
    out_format: str,
    timeout: int,
    abc_timeout: int,
    tmp_root: Optional[Path],
    keep_tmp: bool,
    strict_cec: bool,
    sim_vectors: int,
    sim_seed: int,
    sim_compile_timeout: int,
    sim_run_timeout: int,
    sat_bit_timeout: int = 15,
    sat_total_timeout: int = 300,
    algebraic_timeout: int = 300,
    algebraic_term_cap: int = 200000,
    algebraic_fallback: bool = False,
    algebraic_sliced_outputs: Sequence[str] = (),
    algebraic_case_split_bits: Sequence[str] = (),
    algebraic_cone_input_cap: int = 6,
    algebraic_coefficient_inputs: Sequence[str] = (),
    algebraic_coefficient_engine: str = "cec",
    algebraic_bdd_node_cap: int = 1000000,
    algebraic_bdd_order: str = "bit-major",
) -> CecResult:
    if (algebraic_coefficient_engine not in ("cec", "bdd") or algebraic_bdd_node_cap < 2
            or algebraic_bdd_order not in ("bit-major", "port-major")):
        return CecResult(case, str(reference), str(implementation), engine, abc_extra,
                         "configuration_error", None, "", "invalid coefficient engine or BDD resource/order option")
    if normalize_engine(engine) != "algebraic-terminal" and (algebraic_coefficient_engine != "cec"
            or algebraic_bdd_node_cap != 1000000 or algebraic_bdd_order != "bit-major"):
        return CecResult(case, str(reference), str(implementation), engine, abc_extra,
                         "configuration_error", None, "", "coefficient engine/BDD options require algebraic-terminal")
    if not reference.exists():
        return CecResult(case, str(reference), str(implementation), engine, abc_extra, "missing_ref", None, "", "reference file not found")
    if not implementation.exists():
        return CecResult(case, str(reference), str(implementation), engine, abc_extra, "missing_impl", None, "", "implementation file not found")

    try:
        interface_match, interface_detail = compare_top_port_contracts(
            reference, implementation
        )
    except (OSError, ValueError) as exc:
        return CecResult(
            case,
            str(reference),
            str(implementation),
            engine,
            abc_extra,
            "interface_error",
            None,
            "",
            str(exc),
        )
    if not interface_match:
        return CecResult(
            case,
            str(reference),
            str(implementation),
            engine,
            abc_extra,
            "interface_mismatch",
            None,
            "",
            interface_detail,
        )

    if normalize_engine(engine) in ("algebraic", "algebraic-cones", "algebraic-terminal"):
        return run_algebraic_cec_pair(case, reference, implementation, yosys,
                                       algebraic_timeout, algebraic_term_cap,
                                       tmp_root, keep_tmp, algebraic_sliced_outputs,
                                       algebraic_case_split_bits, normalize_engine(engine),
                                       algebraic_cone_input_cap, algebraic_coefficient_inputs,
                                       algebraic_coefficient_engine, algebraic_bdd_node_cap, algebraic_bdd_order)

    if normalize_engine(engine) in ("sat-bits", "sat-lemmas"):
        # Import here so existing callers and historical engine behavior remain
        # unchanged; the helper uses this module's interface and process guards.
        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.insert(0, str(PACKAGE_ROOT))
        from verify.sat_bits import run_pair
        return run_pair(sys.modules[__name__], case, reference, implementation,
                        yosys, timeout, sat_total_timeout, sat_bit_timeout,
                        tmp_root, keep_tmp,
                        use_proved_lemmas=normalize_engine(engine) == "sat-lemmas")

    if normalize_engine(engine) == "smt":
        if smtbmc is None:
            return CecResult(case, str(reference), str(implementation), "smt", smt_solver, "smt_unavailable", None, "", "yosys-smtbmc is not configured")
        return run_smt_cec_pair(
            case,
            reference,
            implementation,
            yosys,
            smtbmc,
            smt_solver,
            timeout,
            smt_timeout,
            tmp_root,
            keep_tmp,
        )

    if tmp_root:
        tmp_root.mkdir(parents=True, exist_ok=True)
    tmpdir_ctx = None
    if keep_tmp:
        tmpdir_name = tempfile.mkdtemp(
            prefix=f"{case}_",
            dir=tmp_root,
        )
    else:
        tmpdir_ctx = tempfile.TemporaryDirectory(
            prefix=f"{case}_",
            dir=tmp_root,
        )
        tmpdir_name = tmpdir_ctx.name
    tmpdir = Path(tmpdir_name)
    try:
        suffix = ".aig" if out_format == "aiger" else ".blif"
        ref_net = tmpdir / f"ref{suffix}"
        impl_net = tmpdir / f"impl{suffix}"

        ref_result = lower_with_yosys(yosys, reference, ref_net, out_format, timeout)
        if ref_result.returncode != 0:
            return CecResult(
                case,
                str(reference),
                str(implementation),
                engine,
                abc_extra,
                "yosys_ref_error",
                None,
                ref_result.stdout + ref_result.stderr,
                "Yosys failed while lowering reference",
            )

        impl_result = lower_with_yosys(yosys, implementation, impl_net, out_format, timeout)
        if impl_result.returncode != 0:
            return CecResult(
                case,
                str(reference),
                str(implementation),
                engine,
                abc_extra,
                "yosys_impl_error",
                None,
                impl_result.stdout + impl_result.stderr,
                "Yosys failed while lowering implementation",
            )

        if out_format == "aiger":
            try:
                audit_aiger_pair(reference, ref_net, impl_net)
            except (OSError, ValueError, IndexError, UnicodeError) as exc:
                return CecResult(case, str(reference), str(implementation), engine,
                                 abc_extra, "aiger_interface_error", None, "", str(exc))

        if normalize_engine(engine) == "auto":
            result = run_auto_abc_attempts(
                case,
                ref_net,
                impl_net,
                abc,
                abc_extra,
                abc_timeout,
                reference,
                implementation,
            )
            # A conclusive disagreement must stay visible; a later backend
            # cannot erase a contradictory fail from another engine.
            if result.status == "conflict":
                return result
            if algebraic_fallback and result.status in {"unknown", "timeout"}:
                algebraic = run_algebraic_cec_pair(
                    case, reference, implementation, yosys, algebraic_timeout,
                    algebraic_term_cap, tmp_root, keep_tmp,
                    algebraic_sliced_outputs, algebraic_case_split_bits
                )
                if algebraic.status == "pass":
                    algebraic.abc_output = result.abc_output + "\n" + algebraic.abc_output
                    return algebraic
                result.error += "\nAlgebraic fallback: " + algebraic.status + " " + algebraic.error
            if strict_cec:
                if smt_fallback and result.status in {"unknown", "timeout"} and smtbmc is not None:
                    return run_smt_cec_pair(
                        case,
                        reference,
                        implementation,
                        yosys,
                        smtbmc,
                        smt_solver,
                        timeout,
                        smt_timeout,
                        tmp_root,
                        keep_tmp,
                    )
                return result
            result = apply_random_sim_fallback(
                result,
                reference,
                implementation,
                sim_vectors,
                sim_seed,
                sim_compile_timeout,
                sim_run_timeout,
            )
            if smt_fallback and result.status in {"pass (non-strict)", "unknown", "timeout"} and smtbmc is not None:
                return run_smt_cec_pair(
                    case,
                    reference,
                    implementation,
                    yosys,
                    smtbmc,
                    smt_solver,
                    timeout,
                    smt_timeout,
                    tmp_root,
                    keep_tmp,
                )
            return result

        last_result: Optional[CecResult] = None
        attempt_log: List[str] = []
        for attempt_engine, attempt_args in engine_attempts(engine, abc_extra):
            last_result = run_abc_attempt(
                case,
                ref_net,
                impl_net,
                abc,
                attempt_engine,
                attempt_args,
                abc_timeout,
                None,
                reference,
                implementation,
            )
            attempt_log.append(format_attempt_log(last_result))
            if last_result.status in {"pass", "fail"}:
                return last_result
        assert last_result is not None
        last_result.error = "\n\n".join(attempt_log)
        return last_result
    finally:
        if keep_tmp:
            print(f"{case}: kept temporary files in {tmpdir_name}", file=sys.stderr)
        elif tmpdir_ctx is not None:
            tmpdir_ctx.cleanup()


def print_result(result: CecResult) -> None:
    print(f"{'case':<8} {'status':<16} {'equiv':<7} {'engine':<6} {'abc_args':<10} implementation")
    print("-" * 96)
    equiv = "-" if result.equivalent is None else ("yes" if result.equivalent else "no")
    print(
        f"{result.case:<8} {result.status:<16} {equiv:<7} "
        f"{result.engine:<6} {result.abc_args:<10} {result.implementation}"
    )
    print("-" * 96)


def result_to_dict(result: CecResult) -> Dict[str, object]:
    return {
        "case": result.case,
        "reference": result.reference,
        "implementation": result.implementation,
        "engine": result.engine,
        "abc_args": result.abc_args,
        "status": result.status,
        "equivalent": result.equivalent,
        "abc_output": result.abc_output,
        "error": result.error,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", help="reference Verilog file")
    parser.add_argument("implementation", help="implementation Verilog file")
    parser.add_argument("--yosys", help="Yosys executable or path; overrides tool config")
    parser.add_argument("--abc", help="ABC executable or path; overrides tool config")
    parser.add_argument("--smtbmc", help="yosys-smtbmc executable or path; overrides tool config")
    parser.add_argument(
        "--tool-config",
        default=str(DEFAULT_TOOL_CONFIG),
        help="tool path config generated by install_skill.sh",
    )
    parser.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "cec", "dcec", "&cec", "acec", "smt", "sat-bits", "sat-lemmas", "algebraic", "algebraic-cones", "algebraic-terminal"],
        help='CEC engine. "acec" is a legacy alias for "&cec", not arithmetic &acec; auto runs &cec, dcec, and cec; sat-bits independently proves every output bit; sat-lemmas proves bits in order and may assume only earlier equalities already proved in the same chain; algebraic proves supported arithmetic through checked polynomial reduction; algebraic-cones adds exact small-primary-input cone elimination; algebraic-terminal retains native gate functions and strictly discharges every independently replayed residual coefficient.',
    )
    parser.add_argument(
        "--abc-extra",
        default="",
        help='extra ABC engine arguments; use --abc-extra="-p -T 60" or --abc-extra="-C 5000 -x"',
    )
    parser.add_argument(
        "--format",
        default="aiger",
        choices=["aiger", "blif"],
        help="intermediate netlist format. Use aiger for &cec.",
    )
    parser.add_argument("--timeout", type=int, default=300, help="per-tool timeout in seconds")
    parser.add_argument(
        "--abc-timeout",
        type=int,
        default=15,
        help="timeout in seconds for each ABC engine attempt",
    )
    parser.add_argument("--smt-solver", default="z3", help="solver name passed to yosys-smtbmc")
    parser.add_argument("--smt-timeout", type=int, default=300, help="timeout in seconds for yosys-smtbmc")
    parser.add_argument("--sat-bit-timeout", type=int, default=15, help="solver seconds per independent output bit")
    parser.add_argument("--sat-total-timeout", type=int, default=300, help="total seconds for the output-bit SAT stage, excluding frontend")
    parser.add_argument("--algebraic-timeout", type=int, default=300, help="total seconds for algebraic extraction and independent certificate replay")
    parser.add_argument("--algebraic-term-cap", type=int, default=200000, help="maximum terms in an intermediate algebraic polynomial")
    parser.add_argument("--algebraic-coefficient-input", action="append", default=[], help="original input port supporting retained native terminal functions; repeat for a union of ports in algebraic-terminal")
    parser.add_argument("--algebraic-coefficient-engine", choices=["cec", "bdd"], default="cec", help="strict coefficient discharge for algebraic-terminal: CEC of emitted RTL (default), or ROBDD interpretation of original native gates")
    parser.add_argument("--algebraic-bdd-node-cap", type=int, default=1000000, help="maximum ROBDD nodes per coefficient group in algebraic-terminal")
    parser.add_argument("--algebraic-bdd-order", choices=["bit-major", "port-major"], default="bit-major", help="primary-input ROBDD variable order for algebraic-terminal")
    parser.add_argument("--algebraic-cone-input-cap", type=int, default=6, help="maximum primary inputs per exhaustively expanded cone in algebraic-cones/algebraic-terminal (1 to 8)")
    parser.add_argument("--algebraic-sliced-output", action="append", default=[], help="prove this output by significance-sliced reference-minus-candidate reduction; repeat for multiple outputs")
    parser.add_argument("--algebraic-case-split-bit", action="append", default=[], help="exhaustively split an algebraic proof on this named primary-input bit; all combinations are proved and every output must be significance-sliced")
    parser.add_argument("--algebraic-fallback", action="store_true", help="try strict algebraic proof after inconclusive auto ABC, before simulation/SMT")
    parser.add_argument(
        "--smt-fallback",
        action="store_true",
        help="after auto returns unknown/timeout or pass (non-strict), run strict Yosys SMT2 + yosys-smtbmc",
    )
    parser.add_argument("--tmpdir", help="parent directory for temporary lowered netlists")
    parser.add_argument("--keep-tmp", action="store_true", help="keep generated temporary netlist directories")
    parser.add_argument(
        "--strict-cec",
        action="store_true",
        help="do not promote auto unknown results with random simulation",
    )
    parser.add_argument(
        "--sim-vectors",
        type=int,
        default=1024,
        help="random simulation vectors for auto unknown fallback",
    )
    parser.add_argument("--sim-seed", type=int, default=1, help="random simulation seed")
    parser.add_argument(
        "--sim-compile-timeout",
        type=int,
        default=120,
        help="Icarus compile timeout for random simulation fallback",
    )
    parser.add_argument(
        "--sim-run-timeout",
        type=int,
        default=120,
        help="Icarus run timeout for random simulation fallback",
    )
    parser.add_argument("--json", action="store_true", help="print JSON results")
    args = parser.parse_args(argv)
    if args.sat_bit_timeout < 1 or args.sat_total_timeout < 1:
        parser.error("SAT timeouts must be positive")
    if args.algebraic_timeout < 1 or args.algebraic_term_cap < 1:
        parser.error("Algebraic budgets must be positive")
    if not 1 <= args.algebraic_cone_input_cap <= 8:
        parser.error("Algebraic cone input cap must be between 1 and 8")
    if args.algebraic_bdd_node_cap < 2:
        parser.error("Algebraic BDD node cap must be at least 2")

    config_path = Path(args.tool_config)
    config = load_tool_config(config_path)
    yosys = resolve_executable(configured_tool("YOSYS", args.yosys, config, config_path), "Yosys")
    abc = (
        Path("")
        if args.engine in ("smt", "sat-bits", "sat-lemmas", "algebraic", "algebraic-cones", "algebraic-terminal")
        else resolve_executable(configured_tool("ABC", args.abc, config, config_path), "ABC")
    )
    smtbmc = resolve_optional_smtbmc(args.smtbmc, config, yosys) if args.engine == "smt" or args.smt_fallback else None

    tmp_root = Path(args.tmpdir) if args.tmpdir else None
    reference = Path(args.reference)
    implementation = Path(args.implementation)
    result = run_cec_pair(
        implementation.stem,
        reference,
        implementation,
        yosys,
        abc,
        smtbmc,
        args.engine,
        args.abc_extra,
        args.smt_solver,
        args.smt_timeout,
        args.smt_fallback,
        args.format,
        args.timeout,
        args.abc_timeout,
        tmp_root,
        args.keep_tmp,
        args.strict_cec,
        args.sim_vectors,
        args.sim_seed,
        args.sim_compile_timeout,
        args.sim_run_timeout,
        args.sat_bit_timeout,
        args.sat_total_timeout,
        args.algebraic_timeout,
        args.algebraic_term_cap,
        args.algebraic_fallback,
        args.algebraic_sliced_output,
        args.algebraic_case_split_bit,
        args.algebraic_cone_input_cap,
        args.algebraic_coefficient_input,
        args.algebraic_coefficient_engine,
        args.algebraic_bdd_node_cap,
        args.algebraic_bdd_order,
    )

    if args.json:
        print(json.dumps(result_to_dict(result), indent=2, sort_keys=True))
    else:
        print_result(result)
        if result.equivalent is not True and result.error:
            print(f"\n{result.case} detail:\n{result.error}", file=sys.stderr)

    return 0 if result.equivalent is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""SAT proofs of every combinational output bit.

The independent mode proves every bit without assumptions.  The cumulative
mode may use only earlier, already-proved output equalities as lemmas.  Every
bit remains a proof obligation and partial coverage is diagnostic, not a pass.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import time
from pathlib import Path


def build_miter(inputs, outputs):
    ports = [f"pi_{i}" for i in range(len(inputs))]
    duties = [(name, bit) for name, width in outputs for bit in range(width)]
    ports += [f"eq_{i}" for i in range(len(duties))]
    lines = ["module miter(" + ", ".join(ports) + ");"]
    for i, (_name, width) in enumerate(inputs):
        lines.append(f"input [{width-1}:0] pi_{i};")
    for i, (_name, width) in enumerate(outputs):
        lines.append(f"wire [{width-1}:0] gold_{i}, gate_{i};")
    for side in ("gold", "gate"):
        conns = [f".{name}(pi_{i})" for i, (name, _) in enumerate(inputs)]
        conns += [f".{name}({side}_{i})" for i, (name, _) in enumerate(outputs)]
        lines.append(f"{side} u_{side}(" + ", ".join(conns) + ");")
    duty = 0
    for i, (_name, width) in enumerate(outputs):
        for bit in range(width):
            lines.append(f"output eq_{duty};")
            lines.append(f"assign eq_{duty} = (gold_{i}[{bit}] == gate_{i}[{bit}]);")
            duty += 1
    return "\n".join(lines + ["endmodule", ""]), duties


def parse_sat(output, returncode):
    if returncode == 124 or "TIMEOUT" in output:
        return "timeout"
    if returncode != 0:
        return "error"
    passed = "SAT proof finished - no model found: SUCCESS!" in output
    failed = "SAT proof finished - model found: FAIL!" in output
    if passed and failed:
        return "error"
    return "pass" if passed else "fail" if failed else "unknown"


def run_pair(api, case, reference, implementation, yosys, frontend_timeout,
             total_timeout, bit_timeout, tmp_root, keep_tmp,
             use_proved_lemmas=False):
    """Return CecResult and retain per-bit commands/logs when requested."""
    if tmp_root:
        tmp_root.mkdir(parents=True, exist_ok=True)
    context = None if keep_tmp else tempfile.TemporaryDirectory(prefix=f"{case}_sat_", dir=tmp_root)
    work = Path(tempfile.mkdtemp(prefix=f"{case}_sat_", dir=tmp_root) if keep_tmp else context.name)
    strategy = "cumulative-proved-lemma-sat" if use_proved_lemmas else "independent-output-bit-sat"
    report = {"strategy": strategy,
              "assumption_policy": "only earlier output equalities proved in this certificate chain" if use_proved_lemmas else "none",
              "bits": [],
              "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
              "implementation_sha256": hashlib.sha256(implementation.read_bytes()).hexdigest()}

    def finish(status, error=""):
        report["status"] = status
        report["proved_bits"] = sum(b["status"] == "pass" for b in report["bits"])
        (work / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
        detail = f"proved_bits={report['proved_bits']}/{report.get('required_bits', 0)}; artifacts={work}"
        engine = "sat-lemmas" if use_proved_lemmas else "sat-bits"
        return api.CecResult(case, str(reference), str(implementation), engine, "",
                             status, True if status == "pass" else False if status == "fail" else None,
                             detail, error)
    try:
        inputs, outputs = api.parse_top_interface(reference)
        if not outputs:
            return finish("interface_error", "No output proof obligations")
        # Current source parser supports these names; reject rather than silently
        # misconnecting an escaped or otherwise unsupported identifier.
        if any(not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_$]*", n) for n, _ in inputs + outputs):
            return finish("interface_error", "Unsupported identifier in SAT miter")
        miter, duties = build_miter(inputs, outputs)
        report["required_bits"] = len(duties)
        (work / "gold.v").write_text(api.rename_top_module(reference.read_text(), "gold"))
        (work / "gate.v").write_text(api.rename_top_module(implementation.read_text(), "gate"))
        (work / "miter.v").write_text(miter)
        # No formal assumptions or input restrictions. check -assert rejects
        # undriven nets and combinational loops before SAT can abstract them.
        script = "\n".join([
            f'read_verilog -sv "{work / "gold.v"}" "{work / "gate.v"}" "{work / "miter.v"}"',
            "hierarchy -check -top miter", "proc", f'write_json "{work / "interfaces.json"}"',
            "flatten", "opt", "memory_map", "opt",
            "check -assert", f'write_json "{work / "miter.json"}"',
            f'write_rtlil "{work / "miter.il"}"'])
        (work / "prepare.ys").write_text(script + "\n")
        result = api.run_command([str(yosys), "-Q", "-T", "-s", str(work / "prepare.ys")], frontend_timeout)
        (work / "prepare.log").write_text(result.stdout + result.stderr)
        if result.returncode != 0:
            return finish("sat_frontend_error", "Yosys preparation failed; see prepare.log")
        api.audit_yosys_port_contracts(json.loads((work / "interfaces.json").read_text()), reference, implementation)
        module = json.loads((work / "miter.json").read_text())["modules"]["miter"]
        ports = module["ports"]
        expected = {f"eq_{i}" for i in range(len(duties))}
        actual = {name for name, p in ports.items() if p["direction"] == "output"}
        if actual != expected or any(len(ports[n]["bits"]) != 1 for n in expected):
            return finish("sat_proof_duty_error", "Serialized miter output coverage mismatch")
        # Explicitly exclude state, assumptions, black boxes and nondeterminism.
        # Other unsupported cells fail in SAT (never use -ignore-unknown-cells).
        forbidden = ("dff", "dffe", "sdff", "adff", "ff", "latch", "mem", "assume", "assert", "check", "any", "all", "initstate")
        for cell in module["cells"].values():
            if any(word in cell["type"].lower() for word in forbidden):
                return finish("sat_unsupported", f"Non-combinational/formal cell: {cell['type']}")
        if any(b in ("x", "z") for net in module["netnames"].values() for b in net["bits"]):
            return finish("sat_unsupported", "Undefined values are outside the two-state contract")
        deadline = time.monotonic() + total_timeout
        proved_indices = []
        for i, (name, bit) in enumerate(duties):
            remaining = deadline - time.monotonic()
            if remaining < 1:
                break
            seconds = max(1, min(bit_timeout, math.floor(remaining)))
            prior = list(proved_indices) if use_proved_lemmas else []
            exposed = prior + [i]
            expose = " ".join(f"miter/eq_{j}" for j in exposed)
            lemma_sets = " ".join(f"-set eq_{j} 1" for j in prior)
            proof = (f'read_rtlil "{work / "miter.il"}"\n'
                     f'delete -output miter/eq_*\nexpose {expose}\nopt_clean -purge\n'
                     f'sat -enable_undef -set-def-inputs {lemma_sets} -prove eq_{i} 1 -timeout {seconds} -show-inputs '
                     f'-dump_json "{work / f"bit_{i}.cex.json"}"\n')
            command_file = work / f"bit_{i}.ys"
            command_file.write_text(proof)
            started = time.monotonic()
            result = api.run_command([str(yosys), "-Q", "-T", "-s", str(command_file)], min(seconds + 10, max(1, math.ceil(remaining))))
            output = result.stdout + result.stderr
            (work / f"bit_{i}.log").write_text(output)
            status = parse_sat(output, result.returncode)
            report["bits"].append({"index": i, "output": name, "lsb_offset": bit, "status": status,
                                   "assumed_proved_indices": prior,
                                   "elapsed_seconds": time.monotonic()-started, "returncode": result.returncode})
            if status == "pass":
                proved_indices.append(i)
            elif use_proved_lemmas:
                detail = f"Lemma chain stopped on {name}, LSB offset {bit}; no later duty may assume it"
                return finish(status, detail)
            if status == "fail":
                return finish("fail", f"Equality/definedness counterexample on {name}, LSB offset {bit}; replay to distinguish a value mismatch from undefined output")
            if status in ("error", "unknown"):
                return finish(status, f"Inconclusive tool result on {name}, LSB offset {bit}")
        complete = len(report["bits"]) == len(duties) and all(b["status"] == "pass" for b in report["bits"])
        return finish("pass" if complete else "timeout", "" if complete else "Partial bit coverage is not equivalence")
    except (OSError, ValueError, KeyError) as exc:
        return finish("sat_error", str(exc))
    finally:
        if context:
            context.cleanup()

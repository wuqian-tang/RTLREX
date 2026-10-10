#!/usr/bin/env python3
"""Budgeted truth-table recovery with atomic, verified best-candidate retention.

The output is committed immediately after exact verification. Refinement runs
never modify it unless a complete verification passes and syntax cost improves.
Receipts are local workflow evidence; external evaluations must recheck outputs.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from reverse.refinement_budget import RefinementBudget, budget_path, initial_policy


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", prefix="." + path.name + ".", dir=path.parent, delete=False) as stream:
        stream.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    temporary.replace(path)
    sync_directory(path.parent)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def protect_output(path: Path) -> None:
    """Keep a verified checkpoint readable but block ordinary in-place edits.

    This is an accident guard, not a security boundary. A verified promotion
    still replaces the directory entry atomically without making it writable.
    Preserve existing read permissions rather than broadening access.
    """
    path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o222)


def verification_context(yosys: str | None) -> dict:
    """Bind a retained local receipt to the checking and pricing implementation."""
    sys.path.insert(0, str(SCRIPTS))
    from verify.truth_yosys import default_yosys, executable
    from verify.tooling import optional_tool
    from verify.truth_verification_cache import identity
    paths = [SCRIPTS / "verify" / name for name in
             ("truth_yosys.py", "truth_sim.py", "truth_verification_cache.py", "truth_bitparallel.py", "tooling.py")]
    paths += [SCRIPTS / "truth/utils.py", SCRIPTS / "cost/RTL_cost_calculator.py",
              SCRIPTS / "RTL_cost_calculator.py", SCRIPTS / "check_allowed_syntax.py",
              Path(__file__), SCRIPTS / "reverse/refinement_budget.py",
              SCRIPTS / "verify/truth_parallel.py"]
    chosen = executable(yosys) if yosys else default_yosys()
    if chosen is None:
        raise ValueError("Configured Yosys executable is not available")
    tools = {"yosys": chosen}
    for name in ("iverilog", "vvp"):
        if resolved := optional_tool(name.upper()):
            tools[name] = Path(resolved)
    if len(tools) != 3:
        raise ValueError("Yosys, iverilog and vvp are required for a bound recovery receipt")
    # A constant placeholder excludes candidate/truth values from this context;
    # those are separately bound in the receipt. The shared identity includes
    # compiler companions, data directories, environment and working directory.
    return identity(b"01\n", b"", tools, [p for p in paths if p.is_file()],
                    (0, 0, 0), {"scope": "checkpoint_context"})


def execute(command: list[str], directory: Path, stem: str, deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"status": "budget_exhausted"}
    start = time.monotonic()
    with (directory / (stem + ".stdout")).open("w") as stdout, (directory / (stem + ".stderr")).open("w") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            return {"status": "budget_exhausted", "seconds": time.monotonic() - start}
    try:
        value = json.loads((directory / (stem + ".stdout")).read_text())
    except ValueError:
        value = None
    return {"status": "completed", "returncode": process.returncode,
            "seconds": time.monotonic() - start, "value": value}


def worker(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(SCRIPTS))
    if args.worker == "infer":
        from cost.RTL_cost_calculator import set_operator_cost_csv
        set_operator_cost_csv(str(args.cost_csv.resolve()))
        from reverse.truth_reverse import infer_truth
        n, m, candidate = infer_truth(args.truth, allow_boolean_fallback=args.allow_boolean_fallback)
        result = {"n_inputs": n, "n_outputs": m, "status": "no_match"}
        if candidate is not None:
            args.output.write_text(candidate.verilog)
            result.update(status="generated", family=candidate.family,
                          high_level=candidate.high_level, candidate_sha256=sha(args.output))
        print(json.dumps(result))
        return 0 if candidate else 1
    from verify.truth_yosys import default_yosys, verify
    result = verify(args.truth, args.output, Path(args.yosys) if args.yosys else default_yosys(),
                    frontend_timeout=args.engine_timeout,
                    compile_timeout=args.engine_timeout, run_timeout=args.engine_timeout, use_cache=False)
    print(json.dumps(result))
    return 0 if result.get("status") == "pass" and result.get("frontend") == "pass" else 1


def recover(args: argparse.Namespace) -> dict:
    start = time.monotonic()
    deadline = start + args.budget_seconds
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Lock by output path, even when callers choose different state directories.
    # Never wait beyond this invocation's remaining budget.
    with (output.parent / ("." + output.name + ".recovery.lock")).open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"status": "budget_exhausted", "detail": "Waiting for output checkpoint lock"}
                time.sleep(min(0.05, remaining))
        return recover_locked(args, start, deadline)


def recover_locked(args: argparse.Namespace, start: float, deadline: float) -> dict:
    truth, output = args.truth.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    state = (args.state_dir or output.parent / ("." + output.name + ".recovery")).resolve()
    state.mkdir(parents=True, exist_ok=True)
    receipt_path = state / "best.json"
    first_path = state / "first.json"
    pending_path = state / "pending.json"
    sys.path.insert(0, str(SCRIPTS))
    from verify.truth_yosys import truth_dimensions
    from verify.truth_verification_cache import complete, eligible
    n, m = truth_dimensions(truth.read_bytes())
    def current_binding() -> dict:
        return {"truth_sha256": sha(truth), "output": str(output),
                "n_inputs": n, "n_outputs": m,
                "cost_csv_sha256": sha(args.cost_csv),
                "allowed_syntax_sha256": sha(args.allowed_syntax) if args.allowed_syntax else None,
                "verification_context": verification_context(args.yosys)}
    binding = current_binding()
    def first_evidence(receipt: dict) -> tuple[dict, dict]:
        metadata = receipt.get("first_checkpoint")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("receipt_path"), str):
            raise ValueError("Checkpoint lacks its durable first-candidate evidence")
        path = Path(metadata["receipt_path"])
        if not path.is_file() or sha(path) != metadata.get("receipt_sha256"):
            raise ValueError("First checkpoint evidence changed or is missing")
        first = json.loads(path.read_text())
        if (not complete_receipt(first) or first.get("candidate_sha256") != metadata.get("candidate_sha256")
                or first.get("cost") != metadata.get("cost")):
            raise ValueError("First checkpoint evidence is not bound to the complete proof context")
        return metadata, first
    def budget_for(receipt: dict) -> RefinementBudget:
        metadata, first = first_evidence(receipt)
        anchor = RefinementBudget.anchor_for(output, first, Path(metadata["receipt_path"]))
        return RefinementBudget(budget_path(output), anchor, atomic_json, args)
    def complete_receipt(value: dict) -> bool:
        return (isinstance(value, dict) and isinstance(value.get("verification"), dict)
                and all(value.get(k) == v for k, v in binding.items())
                and complete(value.get("verification", {}),
                             {**binding, "candidate_sha256": value.get("candidate_sha256"),
                              "options": {"replay_workers": min(1 << n, 1 if n < 12 else 4)}}))
    # Finalization checks the current checkpoint without consuming a proposal,
    # rerunning a solver, repairing journals or opening another refinement
    # window. An unresolved interrupted promotion needs normal recovery first.
    if getattr(args, "check_checkpoint", False):
        if pending_path.exists():
            return {"status": "checkpoint_recovery_required", "output": str(output),
                    "detail": "Unresolved promotion journal; run normal recovery before finalization."}
        selected = json.loads(receipt_path.read_text()) if receipt_path.is_file() else None
        if (not output.is_file() or not complete_receipt(selected)
                or selected.get("candidate_sha256") != sha(output)
                or not eligible(output.read_bytes())):
            return {"status": "output_unbound", "output": str(output),
                    "detail": "Final bytes lack their current complete verified checkpoint; do not submit them."}
        first_evidence(selected)
        checkpoint_budget = budget_for(selected)
        checkpoint_budget.load()
        protect_output(output)
        if current_binding() != binding or sha(output) != selected["candidate_sha256"]:
            return {"status": "source_changed_during_verification", "output": str(output)}
        return {"schema": "checkpointed-truth-recovery/v2", "status": "checkpoint_validated",
                "output": str(output), "promoted": False, "previous_retained": True,
                "output_write_protected": True, "first_checkpoint": selected["first_checkpoint"],
                "selected_checkpoint": {"receipt_path": str(receipt_path), "receipt_sha256": sha(receipt_path),
                                        "candidate_sha256": selected["candidate_sha256"], "cost": selected.get("cost"),
                                        "verification": selected["verification"]},
                "refinement_budget": checkpoint_budget.report(), "seconds": time.monotonic() - start}
    # The durable journal is written before output replacement. If a process
    # dies between the two atomic renames, its next invocation repairs the
    # receipt for the already verified bytes instead of abandoning that output.
    if pending_path.is_file():
        pending = json.loads(pending_path.read_text())
        if (output.is_file() and complete_receipt(pending)
                and pending.get("candidate_sha256") == sha(output)
                and eligible(output.read_bytes())):
            pending_budget = budget_for(pending)
            if not pending_budget.path.exists():
                if pending.get("refinement_proposal_id") is not None or pending.get("promotion_kind") != "initial":
                    raise ValueError("A refinement promotion lost its canonical budget journal")
                pending_budget.create(pending["refinement_policy"], pending["refinement_published_wall_ns"])
            else:
                pending_budget.load()
            atomic_json(receipt_path, pending)
        pending_path.unlink()
        sync_directory(state)
    previous = None
    if receipt_path.is_file() and output.is_file():
        value = json.loads(receipt_path.read_text())
        if (complete_receipt(value)
                and value.get("candidate_sha256") == sha(output)
                and eligible(output.read_bytes())):
            previous = value
    if output.exists() and previous is None:
        return {"status": "output_unbound", "output": str(output),
                "detail": "Existing output has no matching verified receipt; select a fresh output path."}
    budget = None
    if previous is not None:
        protect_output(output)
        budget = budget_for(previous)
        budget.load()
        budget.reconcile(previous)
        deadline, rejected = budget.reserve(previous, deadline)
        if rejected is not None:
            return {"schema": "checkpointed-truth-recovery/v2", "status": "refinement_limit_reached",
                    "reason": rejected, "output": str(output), "promoted": False,
                    "previous_retained": True, "first_checkpoint": previous["first_checkpoint"],
                    "selected_checkpoint": {"receipt_path": str(receipt_path), "receipt_sha256": sha(receipt_path),
                                            "candidate_sha256": previous["candidate_sha256"], "cost": previous.get("cost"),
                                            "verification": previous["verification"]},
                    "refinement_budget": budget.report(), "seconds": time.monotonic() - start}
    else:
        # A leftover canonical journal without its checkpoint cannot silently
        # become a new budget. Use a fresh output after explicit diagnosis.
        if budget_path(output).exists():
            raise ValueError("Refinement journal exists without a verified checkpoint; refusing a budget reset")
        initial_policy(args)
    # Unique retained attempt directories make failures inspectable and avoid
    # overwriting the evidence for the previously selected output.
    attempt = Path(tempfile.mkdtemp(prefix="attempt_", dir=state))
    snapshot = attempt / "candidate.v"
    report = {"schema": "checkpointed-truth-recovery/v2", **binding,
              "output": str(output), "attempt": str(attempt),
              "previous_retained": previous is not None, "promoted": False}
    def finish_report() -> dict:
        if budget is not None:
            budget.finish(report["status"], report.get("promoted", False))
            report["refinement_budget"] = budget.report()
        if receipt_path.is_file() and output.is_file():
            selected = json.loads(receipt_path.read_text())
            report["first_checkpoint"] = selected.get("first_checkpoint")
            report["selected_checkpoint"] = {"receipt_path": str(receipt_path), "receipt_sha256": sha(receipt_path),
                                             "candidate_sha256": selected["candidate_sha256"], "cost": selected.get("cost"),
                                             "verification": selected["verification"]}
            report["output_write_protected"] = not bool(output.stat().st_mode & 0o222)
        report.setdefault("seconds", time.monotonic() - start)
        report["report_path"] = str(attempt / "report.json")
        atomic_json(attempt / "report.json", report)
        return report
    # Record reservation identity before any expensive generation/pricing/proof.
    if budget is not None:
        report["refinement_proposal_id"] = budget.data["inflight"]["proposal_id"]
    try:
        if args.candidate:
            shutil.copyfile(args.candidate.resolve(), snapshot)
            report["generation"] = {"status": "supplied_candidate"}
        else:
            command = [sys.executable, str(Path(__file__).resolve()), str(truth), str(snapshot),
                       "--worker", "infer", "--cost-csv", str(args.cost_csv.resolve())]
            if args.allow_boolean_fallback:
                command.append("--allow-boolean-fallback")
            generated = execute(command, attempt, "infer", deadline)
            report["generation"] = generated
            if generated.get("returncode") != 0 or not snapshot.is_file():
                report["status"] = generated.get("status") if generated.get("status") != "completed" else "no_match"
                return finish_report()
        report["candidate_sha256"] = sha(snapshot)
        if not eligible(snapshot.read_bytes()):
            report["status"] = "dependency_bearing_candidate"
            report["detail"] = "A durable checkpoint requires self-contained RTL without preprocessing or external system tasks."
            return finish_report()
        if args.allowed_syntax:
            audited = execute([sys.executable, str(SCRIPTS / "check_allowed_syntax.py"), str(snapshot),
                               "--allowed-syntax", str(args.allowed_syntax), "--json"],
                              attempt, "syntax", deadline)
            report["syntax"] = audited
            if audited.get("returncode") != 0:
                report["status"] = "syntax_rejected"
                return finish_report()
        priced = execute([sys.executable, str(SCRIPTS / "RTL_cost_calculator.py"), str(snapshot),
                          "--cost-csv", str(args.cost_csv), "--json"], attempt, "cost", deadline)
        rows = priced.get("value")
        cost = rows[0].get("cost") if priced.get("returncode") == 0 and isinstance(rows, list) and len(rows) == 1 else None
        report["cost"] = cost
        report["cost_measurement"] = priced
        # A verified incumbent needs no repeated validation of a candidate already
        # known to be more expensive. The skipped candidate is never called exact.
        if previous is not None and cost is not None and previous.get("cost") is not None and cost >= previous["cost"]:
            report["status"] = ("retained_lower_or_equal_cost" if current_binding() == binding
                                else "source_changed_during_verification")
            return finish_report()
        command = [sys.executable, str(Path(__file__).resolve()), str(truth), str(snapshot),
                   "--worker", "verify", "--engine-timeout", str(args.engine_timeout)]
        if args.yosys:
            command += ["--yosys", args.yosys]
        checked = execute(command, attempt, "verify", deadline)
        verification = checked.get("value") or {}
        report["verification_execution"] = checked
        report["verification"] = verification
        if checked.get("returncode") != 0 or verification.get("status") != "pass" or verification.get("frontend") != "pass":
            report["status"] = "budget_exhausted" if checked.get("status") == "budget_exhausted" else "verification_failed"
            return finish_report()
        # Check the immutable snapshot, not a caller's potentially changing file.
        if sha(snapshot) != report["candidate_sha256"] or current_binding() != binding:
            report["status"] = "source_changed_during_verification"
            return finish_report()
        if previous is not None and (cost is None or previous.get("cost") is None):
            report["status"] = "retained_unpriced_incumbent"
            return finish_report()
        # Promotion precedes optional reporting. A later deadline or reporting
        # failure cannot erase the already verified output.
        with tempfile.NamedTemporaryFile(prefix="." + output.name + ".", dir=output.parent, delete=False) as temporary:
            temporary.write(snapshot.read_bytes())
            temporary.flush()
            os.fchmod(temporary.fileno(), stat.S_IMODE(os.fstat(temporary.fileno()).st_mode) & ~0o222)
            os.fsync(temporary.fileno())
            promotion = Path(temporary.name)
        receipt = {**binding, "candidate_sha256": sha(snapshot), "cost": cost,
                   "verification": verification, "attempt": str(attempt),
                   "receipt_scope": "local verified checkpoint; independent evaluation must recheck"}
        if previous is None:
            receipt.update(refinement_policy=initial_policy(args),
                           refinement_published_wall_ns=time.time_ns(),
                           promotion_kind="initial", refinement_proposal_id=None)
            atomic_json(first_path, receipt)
            receipt.update(first_checkpoint={"receipt_path": str(first_path), "receipt_sha256": sha(first_path),
                                             "candidate_sha256": receipt["candidate_sha256"], "cost": cost,
                                             "attempt": str(attempt)})
        else:
            receipt.update(first_checkpoint=previous["first_checkpoint"],
                           refinement_policy=previous["refinement_policy"],
                           refinement_published_wall_ns=previous["refinement_published_wall_ns"],
                           promotion_kind="refinement", refinement_proposal_id=report["refinement_proposal_id"])
        atomic_json(pending_path, receipt)
        promotion.replace(output)
        sync_directory(output.parent)
        atomic_json(receipt_path, receipt)
        if previous is None:
            budget = budget_for(receipt)
            budget.create(receipt["refinement_policy"], receipt["refinement_published_wall_ns"])
        pending_path.unlink()
        sync_directory(state)
        report.update(status="promoted", promoted=True, seconds=time.monotonic() - start)
        return finish_report()
    except Exception:
        if budget is not None:
            selected = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
            if (budget.data['inflight'] is not None and output.is_file() and complete_receipt(selected)
                    and selected.get("candidate_sha256") == sha(output)
                    and selected.get("refinement_proposal_id") == budget.data['inflight']['proposal_id']):
                budget.reconcile(selected)
            else:
                budget.finish("attempt_exception", False)
        raise


def brief_report(result: dict) -> dict:
    """Small stdout view; complete reports and receipts remain untouched."""
    def proof(value):
        return {key: value[key] for key in ('status', 'frontend', 'verification_method',
                'vectors', 'replay_workers') if key in value}
    compact={key: result[key] for key in ('schema','status','reason','detail','error','n_inputs','n_outputs',
            'cost','output','attempt','report_path','candidate_sha256','promoted','previous_retained','seconds',
            'output_write_protected')
            if key in result}
    generation=result.get('generation', {}).get('value') or {}
    if isinstance(generation,dict) and generation.get('family') is not None:
        compact['family']=generation['family']
    if isinstance(result.get('verification'),dict):
        compact['verification']=proof(result['verification'])
    if isinstance(result.get('first_checkpoint'),dict):
        compact['first_checkpoint']=dict(result['first_checkpoint'])
    selected=result.get('selected_checkpoint')
    if isinstance(selected,dict):
        compact['selected_checkpoint']={key: selected[key] for key in
            ('receipt_path','receipt_sha256','candidate_sha256','cost') if key in selected}
        compact['selected_checkpoint']['verification']=proof(selected.get('verification', {}))
    budget=result.get('refinement_budget')
    if isinstance(budget,dict):
        compact['refinement_budget']={key: budget[key] for key in ('path','policy','proposals_started',
            'consecutive_non_improvements','refinement_seconds_remaining','refinement_deadline_wall_ns')
            if key in budget}
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--candidate", type=Path, help="Validate and consider a refinement instead of inferring anew")
    parser.add_argument("--check-checkpoint", action="store_true",
                        help="Check final bytes against the complete current checkpoint without a new proof or proposal")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--budget-seconds", type=float, default=240)
    parser.add_argument("--max-cost-proposals", type=int, default=None,
                        help="Initial policy only: reduce the default two refinement attempts; persists across CLI calls")
    parser.add_argument("--refinement-seconds", type=float, default=None,
                        help="Initial policy only: reduce the 120-s window after first checkpoint publication")
    parser.add_argument("--max-non-improvements", type=int, default=None,
                        help="Initial policy only: stop after one or the default two consecutive unsuccessful proposals")
    parser.add_argument("--engine-timeout", type=int, default=120)
    parser.add_argument("--allow-boolean-fallback", action="store_true")
    parser.add_argument("--allowed-syntax", type=Path)
    parser.add_argument("--cost-csv", type=Path, default=SCRIPTS / "cost/syntax_cost.csv")
    parser.add_argument("--yosys")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--brief", action="store_true", help="Compact JSON stdout; retain full proof reports and receipts")
    parser.add_argument("--worker", choices=("infer", "verify"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_checkpoint and (args.candidate or args.worker):
        parser.error("--check-checkpoint cannot be combined with a candidate or worker")
    if args.budget_seconds <= 0 or args.engine_timeout <= 0:
        parser.error("budgets must be positive")
    if args.worker:
        return worker(args)
    try:
        result = recover(args)
    except (OSError, ValueError) as error:
        result = {"status": "error", "error": str(error)}
    displayed = brief_report(result) if args.brief else result
    print(json.dumps(displayed, indent=2, sort_keys=True) if args.json else f"{result['status']}: {args.output}")
    return 0 if result["status"] in {"promoted", "retained_lower_or_equal_cost", "retained_unpriced_incumbent", "refinement_limit_reached", "checkpoint_validated"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Authenticated local cache of complete truth/frontend verification results.

The cache shares the verifier's local trust boundary, not a remotely supplied
proof format. Independent evaluation should always disable it. A private local
key authenticates records; missing, incomplete, edited, or mismatched records
are cache misses and never evidence of equivalence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile


FLOW = "read_verilog; hierarchy -check -top top; proc; opt; check -assert; write_verilog -noattr; auxiliary write_json; exact unsigned descending x/y interface; no state/memory; supported complete-domain bitparallel else exhaustive interleaved truth_parallel x/y; workers bound; ABC read_truth -xf"
SCHEMA = "complete-truth-frontend-cache/v2-parallel"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def identity(truth: bytes, candidate: bytes, tools: dict[str, Path],
             sources: list[Path], timeouts: tuple[int, int, int], options: dict | None = None) -> dict:
    # Icarus invokes compiler/preprocessor/target modules beyond its CLI binary.
    # Bind the available installation companions as well as the executable.
    companions = set()
    prefix = tools["iverilog"].resolve().parent.parent
    for base in (prefix / "lib", prefix / "lib64"):
        directories = [base / "ivl", *base.glob("*/ivl")]
        for directory in directories:
            if directory.is_dir():
                companions.update(path.resolve() for path in directory.rglob("*") if path.is_file())
    data_directory = os.environ.get("YOSYS_DATDIR")
    if data_directory and Path(data_directory).is_dir():
        companions.update(path.resolve() for path in Path(data_directory).rglob("*") if path.is_file())
    return {
        "schema": SCHEMA, "flow": FLOW,
        "truth_sha256": digest(truth), "candidate_sha256": digest(candidate),
        "n_inputs": len(next(line.strip() for line in truth.decode().splitlines() if line.strip())).bit_length() - 1,
        "n_outputs": len([line for line in truth.decode().splitlines() if line.strip()]),
        "tools": {name: {"path": str(path.resolve()), "sha256": digest(path.read_bytes())}
                  for name, path in tools.items()},
        "sources": {str(path.resolve()): digest(path.read_bytes()) for path in sources},
        "tool_companions": {str(path): digest(path.read_bytes()) for path in sorted(companions)},
        "python": sys.version, "python_executable": str(Path(sys.executable).resolve()),
        "environment_sha256": digest(canonical(dict(os.environ))),
        "cwd": str(Path.cwd().resolve()), "timeouts": list(timeouts),
        "options": options or {},
    }


def eligible(candidate: bytes) -> bool:
    # Dependency-bearing HDL cannot be identified by candidate bytes alone.
    # Avoid caching all preprocessing/external data/system tasks, including
    # includes hidden behind macros. $signed/$unsigned are intrinsic casts.
    import re
    text = candidate.decode(errors="replace")
    return "`" not in text and not re.search(r"\$(?!(?:signed|unsigned)\b)[A-Za-z_]", text)


def complete(result: dict, manifest: dict) -> bool:
    n, m, vectors = result.get("n_inputs"), result.get("n_outputs"), result.get("vectors")
    common = (result.get("status") == "pass" and result.get("frontend") == "pass"
            and result.get("verification_method") in {
                "Yosys-lowered exhaustive Verilog replay",
                "complete-domain interleaved Icarus Verilog replay",
                "complete-domain bit-parallel replay of Yosys JSON cells",
            }
            and result.get("interface", {}).get("status") == "pass"
            and type(n) is int and 0 <= n <= 30 and type(m) is int and m > 0
            and n == manifest["n_inputs"] and m == manifest["n_outputs"]
            and type(vectors) is int and vectors == 1 << n
            and result.get("truth_sha256") == manifest["truth_sha256"]
            and result.get("candidate_sha256") == manifest["candidate_sha256"]
            and isinstance(result.get("lowered_sha256"), str)
            and len(result["lowered_sha256"]) == 64)
    if not common:return False
    if result.get("verification_method") != "complete-domain interleaved Icarus Verilog replay":return True
    from verify.truth_parallel import validate_partitions
    proof=result.get("interleaved_replay",{})
    workers=manifest.get("options",{}).get("replay_workers")
    return (type(workers) is int and 1 <= workers <= 4
        and proof.get("status")=="pass" and proof.get("workers")==workers
        and proof.get("n_inputs")==n and proof.get("n_outputs")==m and proof.get("vectors")==vectors
        and proof.get("truth_sha256")==result["truth_sha256"]
        and proof.get("candidate_sha256")==result["lowered_sha256"]
        and proof.get("coverage",{}).get("coverage_valid") is True
        and proof.get("cache_enabled") is False
        and validate_partitions(proof.get("partitions",[]),vectors,workers))


def local_key(directory: Path, *, create: bool) -> bytes:
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path = directory / ".authentication_key"
    if create and not key_path.exists():
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(secrets.token_bytes(32))
    info = key_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError("Cache authentication key must be a private, locally owned regular file")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise OSError("Invalid local cache authentication key")
    return key


def load(directory: Path, manifest: dict) -> dict | None:
    entry = directory / (digest(canonical(manifest)) + ".json")
    try:
        key = local_key(directory, create=False)
        record = json.loads(entry.read_text())
        payload = record["payload"]
        if not hmac.compare_digest(record["authentication"], hmac.new(key, canonical(payload), "sha256").hexdigest()):
            return None
        if payload.get("identity") != manifest or not complete(payload["result"], manifest):
            return None
        if digest(payload["lowered_verilog"].encode()) != payload["result"]["lowered_sha256"]:
            return None
        return payload["result"].copy()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def store(directory: Path, manifest: dict, result: dict, lowered: bytes) -> bool:
    if not complete(result, manifest) or digest(lowered) != result["lowered_sha256"]:
        return False
    try:
        key = local_key(directory, create=True)
        payload = {"identity": manifest, "result": result.copy(),
                   "lowered_verilog": lowered.decode()}
        record = {"payload": payload,
                  "authentication": hmac.new(key, canonical(payload), "sha256").hexdigest()}
        entry = directory / (digest(canonical(manifest)) + ".json")
        with tempfile.NamedTemporaryFile(mode="wb", dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(canonical(record))
        temporary.replace(entry)
        return True
    except (OSError, ValueError, UnicodeError):
        return False

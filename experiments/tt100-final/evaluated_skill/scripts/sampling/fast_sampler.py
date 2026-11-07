#!/usr/bin/env python3
"""Python wrapper for the C++ primitive-netlist sampler."""

from __future__ import annotations

import subprocess
import os
import random
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Sequence
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reverse.datapath_reverse import parse_spec

ROOT = Path.cwd().resolve()
SRC = Path(__file__).with_name("fast_primitive_sampler.cpp")
INSTALLED_BIN = Path(__file__).with_name("fast_primitive_sampler")


def _cache_binary() -> Path:
    override = os.environ.get("CIRCUIT_REVERSE_FAST_SAMPLER_BIN")
    if override:
        return Path(override).expanduser()

    cache_root = os.environ.get("CIRCUIT_REVERSE_SKILL_CACHE")
    if cache_root:
        return Path(cache_root).expanduser() / "fast_primitive_sampler"

    return ROOT / ".codex_skill_cache" / "circuit-reverse-rtl" / "sampling" / "fast_primitive_sampler"


def ensure_built() -> Path:
    if INSTALLED_BIN.exists() and INSTALLED_BIN.stat().st_mtime >= SRC.stat().st_mtime:
        return INSTALLED_BIN

    binary = _cache_binary()
    try:
        binary.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        binary = Path(tempfile.gettempdir()) / "circuit-reverse-rtl" / "sampling" / "fast_primitive_sampler"
        binary.parent.mkdir(parents=True, exist_ok=True)

    if not binary.exists() or binary.stat().st_mtime < SRC.stat().st_mtime:
        subprocess.run(
            ["g++", "-O3", "-std=c++17", str(SRC), "-o", str(binary)],
            cwd=ROOT,
            check=True,
        )
    return binary


def sample_many(
    netlist: str | Path,
    vectors: Iterable[Mapping[str, int]],
    signals: Iterable[str] | None = None,
    all_signals: bool = False,
) -> List[Dict[str, int]]:
    binary = ensure_built()
    vec_list = list(vectors)
    signal_args = list(signals or [])
    if all_signals:
        signal_args.append("--all-signals")
    payload = "\n".join(
        " ".join(f"{name}={int(value)}" for name, value in vec.items())
        for vec in vec_list
    )
    if payload:
        payload += "\n"
    proc = subprocess.run(
        [str(binary), str(netlist), *signal_args],
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    results: List[Dict[str, int]] = []
    for line in proc.stdout.splitlines():
        row: Dict[str, int] = {}
        for item in line.split():
            name, value = item.split("=", 1)
            row[name] = int(value, 0)
        results.append(row)
    if len(results) != len(vec_list):
        raise RuntimeError(f"sampler returned {len(results)} rows for {len(vec_list)} vectors")
    return results


def random_vectors(netlist: str | Path, count: int, seed: int = 1) -> List[Dict[str, int]]:
    spec = parse_spec(Path(netlist))
    rng = random.Random(seed)
    return [
        {name: rng.randrange(1 << width) for name, width in spec.inputs.items()}
        for _ in range(count)
    ]


@dataclass
class PatternCache:
    netlist: Path
    vectors: List[Dict[str, int]]
    values: Dict[str, List[int]]

    @classmethod
    def build(
        cls,
        netlist: str | Path,
        vectors: Sequence[Mapping[str, int]] | None = None,
        *,
        count: int = 1024,
        seed: int = 1,
        signals: Iterable[str] | None = None,
        all_signals: bool = True,
    ) -> "PatternCache":
        netlist_path = Path(netlist)
        vec_list = [dict(v) for v in (vectors if vectors is not None else random_vectors(netlist_path, count, seed))]
        rows = sample_many(netlist_path, vec_list, signals=signals, all_signals=all_signals)
        values: Dict[str, List[int]] = {}
        for row in rows:
            for name, value in row.items():
                values.setdefault(name, []).append(value)
        return cls(netlist_path, vec_list, values)

    def signal(self, name: str) -> List[int]:
        if name in self.values:
            return self.values[name]
        bit0 = f"{name}[0]"
        if bit0 not in self.values:
            raise KeyError(name)
        width = 0
        while f"{name}[{width}]" in self.values:
            width += 1
        return self.bus(name, width)

    def bus(self, name: str, width: int) -> List[int]:
        result = [0] * len(self.vectors)
        for bit in range(width):
            vals = self.values[f"{name}[{bit}]"]
            for i, value in enumerate(vals):
                result[i] |= (value & 1) << bit
        return result

    def check(
        self,
        signal: str,
        predictor: Callable[[Mapping[str, int]], int],
        *,
        width: int | None = None,
    ) -> bool:
        observed = self.bus(signal, width) if width is not None else self.signal(signal)
        mask = (1 << width) - 1 if width is not None else None
        for vec, expected in zip(self.vectors, observed):
            got = int(predictor(vec))
            if mask is not None:
                got &= mask
            if got != expected:
                return False
        return True

    def first_mismatch(
        self,
        signal: str,
        predictor: Callable[[Mapping[str, int]], int],
        *,
        width: int | None = None,
    ) -> tuple[int, Mapping[str, int], int, int] | None:
        observed = self.bus(signal, width) if width is not None else self.signal(signal)
        mask = (1 << width) - 1 if width is not None else None
        for i, (vec, expected) in enumerate(zip(self.vectors, observed)):
            got = int(predictor(vec))
            if mask is not None:
                got &= mask
            if got != expected:
                return i, vec, expected, got
        return None

    def refresh(self, *, count: int | None = None, seed: int = 2) -> "PatternCache":
        return PatternCache.build(
            self.netlist,
            count=len(self.vectors) if count is None else count,
            seed=seed,
            signals=self.values.keys(),
            all_signals=False,
        )


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist")
    args = parser.parse_args()
    vectors = [json.loads(line) for line in sys.stdin if line.strip()]
    for row in sample_many(args.netlist, vectors):
        print(json.dumps(row, sort_keys=True))

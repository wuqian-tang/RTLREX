#!/usr/bin/env python3
"""Merge compatible Verilog declarations without changing logic."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


PLAIN_DECL_RE = re.compile(
    r"^(?P<indent>\s*)(?P<kind>input|output|wire|reg)"
    r"(?P<attrs>(?:\s+(?:signed|unsigned))?)"
    r"(?P<range>\s+\[[^\]]+\])?\s+"
    r"(?P<names>[A-Za-z_][A-Za-z0-9_$]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_$]*)*)"
    r"\s*;\s*$"
)
INIT_WIRE_RE = re.compile(
    r"^(?P<indent>\s*)wire"
    r"(?P<attrs>(?:\s+(?:signed|unsigned))?)"
    r"(?P<range>\s+\[[^\]]+\])?\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(?P<expr>.+?)\s*;\s*$"
)
FUNCTION_START_RE = re.compile(r"^\s*function\b")
FUNCTION_END_RE = re.compile(r"^\s*endfunction\b")


def decl_key(match: re.Match[str]) -> tuple[str, str, str, str]:
    return (
        match.group("indent"),
        match.groupdict().get("kind") or "wire",
        match.group("attrs") or "",
        match.group("range") or "",
    )


def format_decl(key: tuple[str, str, str, str], items: list[str]) -> str:
    indent, kind, attrs, width = key
    return f"{indent}{kind}{attrs}{width} {', '.join(items)};\n"


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [item for item in items if not (item in seen or seen.add(item))]


def is_blank(line: str) -> bool:
    return line.strip() == ""


def merge_initialized_wire_runs(lines: list[str]) -> list[str]:
    out: list[str] = []
    pending_key: tuple[str, str, str, str] | None = None
    pending_items: list[str] = []

    def flush() -> None:
        nonlocal pending_key, pending_items
        if pending_key is not None:
            out.append(format_decl(pending_key, pending_items))
            pending_key = None
            pending_items = []

    for line in lines:
        match = INIT_WIRE_RE.match(line)
        if not match:
            flush()
            out.append(line)
            continue

        key = decl_key(match)
        item = f"{match.group('name')} = {match.group('expr').strip()}"
        if key != pending_key:
            flush()
            pending_key = key
        pending_items.append(item)

    flush()
    return out


def merge_top_level_plain_decls(lines: list[str]) -> list[str]:
    groups: dict[tuple[str, str, str, str], list[str]] = {}
    order: list[tuple[str, str, str, str]] = []
    consumed: set[int] = set()
    in_function = False

    for idx, line in enumerate(lines):
        if FUNCTION_START_RE.match(line):
            in_function = True
        if in_function:
            if FUNCTION_END_RE.match(line):
                in_function = False
            continue

        match = PLAIN_DECL_RE.match(line)
        if not match:
            continue

        key = decl_key(match)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].extend(name.strip() for name in match.group("names").split(","))
        consumed.add(idx)

    if not consumed:
        return lines

    first = min(consumed)
    merged_decls = [format_decl(key, unique(groups[key])) for key in order]
    out: list[str] = []
    for idx, line in enumerate(lines):
        if idx == first:
            out.extend(merged_decls)
        if idx not in consumed:
            if (
                is_blank(line)
                and out
                and is_blank(out[-1])
                and (
                    (idx > 0 and idx - 1 in consumed)
                    or (idx + 1 < len(lines) and idx + 1 in consumed)
                )
            ):
                continue
            out.append(line)
    return out


def compact(text: str) -> str:
    lines = text.splitlines(keepends=True)
    lines = merge_initialized_wire_runs(lines)
    lines = merge_top_level_plain_decls(lines)
    return "".join(lines)


def verilog_paths(args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in args:
        path = Path(arg)
        paths.extend(sorted(path.glob("*.v")) if path.is_dir() else [path])
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Verilog files or directories of .v files")
    parser.add_argument("--check", action="store_true", help="fail if any file would change")
    args = parser.parse_args()

    changed: list[Path] = []
    for path in verilog_paths(args.paths):
        before = path.read_text()
        after = compact(before)
        if before != after:
            changed.append(path)
            if not args.check:
                path.write_text(after)

    for path in changed:
        print(path)
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())

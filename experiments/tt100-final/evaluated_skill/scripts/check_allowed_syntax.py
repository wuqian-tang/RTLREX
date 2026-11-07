#!/usr/bin/env python3
"""Reject Verilog reserved words absent from a benchmark syntax whitelist."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


VERILOG_KEYWORDS = {
    "always", "and", "assign", "automatic", "begin", "buf", "bufif0",
    "bufif1", "case", "casex", "casez", "cell", "cmos", "config",
    "deassign", "default", "defparam", "design", "disable", "edge", "else",
    "end", "endcase", "endconfig", "endfunction", "endgenerate", "endmodule",
    "endprimitive", "endspecify", "endtable", "endtask", "event", "for",
    "force", "forever", "fork", "function", "generate", "genvar", "highz0",
    "highz1", "if", "ifnone", "incdir", "include", "initial", "inout",
    "input", "instance", "integer", "join", "large", "liblist", "library",
    "localparam", "macromodule", "medium", "module", "nand", "negedge",
    "nmos", "nor", "noshowcancelled", "not", "notif0", "notif1", "or",
    "output", "parameter", "pmos", "posedge", "primitive", "pull0", "pull1",
    "pulldown", "pullup", "pulsestyle_onevent", "pulsestyle_ondetect",
    "rcmos", "real", "realtime", "reg", "release", "repeat", "rnmos",
    "rpmos", "rtran", "rtranif0", "rtranif1", "scalared",
    "showcancelled", "signed", "small", "specify", "specparam", "strong0",
    "strong1", "supply0", "supply1", "table", "task", "time", "tran",
    "tranif0", "tranif1", "tri", "tri0", "tri1", "triand", "trior",
    "trireg", "unsigned", "use", "vectored", "wait", "wand", "weak0",
    "weak1", "while", "wire", "wor", "xnor", "xor",
}

OPERATOR_RE = re.compile(
    r"===|!==|<<<|>>>|<<|>>|\*\*|&&|\|\||==|!=|>=|<=|\^~|~\^|~&|~\||"
    r"\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|[+\-*/%><!~&|^?]"
)


def strip_comments_and_strings(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def load_allowed_words(path: Path) -> set[str]:
    words: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.update(re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", line))
    return words


def load_allowed_operators(path: Path) -> set[str]:
    text = "\n".join(
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    operators = set(OPERATOR_RE.findall(text))
    if "?" in operators:
        operators.remove("?")
        operators.add("?:")
    return operators


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rtl")
    parser.add_argument("--allowed-syntax", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rtl_path = Path(args.rtl)
    allowed_path = Path(args.allowed_syntax)
    allowed = load_allowed_words(allowed_path)
    allowed_operators = load_allowed_operators(allowed_path)
    code = strip_comments_and_strings(rtl_path.read_text())
    used_words = set(re.findall(r"\$?[A-Za-z_][A-Za-z0-9_$]*", code))
    used_keywords = {
        word.lstrip("$")
        for word in used_words
        if word.lstrip("$") in VERILOG_KEYWORDS
    }
    invalid = sorted(used_keywords - allowed)
    used_operators = set(OPERATOR_RE.findall(code))
    if "?" in used_operators:
        used_operators.remove("?")
        used_operators.add("?:")
    invalid_operators = sorted(used_operators - allowed_operators)
    result = {
        "rtl": str(rtl_path),
        "allowed_syntax": str(allowed_path),
        "status": "pass" if not invalid and not invalid_operators else "fail",
        "invalid_keywords": invalid,
        "invalid_operators": invalid_operators,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif invalid or invalid_operators:
        details = []
        if invalid:
            details.append(f"keywords: {', '.join(invalid)}")
        if invalid_operators:
            details.append(f"operators: {', '.join(invalid_operators)}")
        print(f"{rtl_path}: disallowed Verilog syntax: {'; '.join(details)}")
    else:
        print(f"{rtl_path}: allowed keyword audit passed")
    return 0 if not invalid and not invalid_operators else 1


if __name__ == "__main__":
    raise SystemExit(main())

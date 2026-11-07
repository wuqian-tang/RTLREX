#!/usr/bin/env python3
"""Evaluate RTL syntax cost.

The default syntax_cost.csv favors compact, high-level, readable RTL. A strict
CAD Contest 2022 Problem A CSV can be selected with --cost-csv. The calculator
supports the CADContest_2022_Problem_A_20220514.pdf model:
  * operator costs from Appendix A
  * keyword/primitive costs from Appendix B
  * submodule instantiations contribute the instantiated module_cost
  * final file cost is the module_cost of module top
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PRIMITIVES = {"and", "or", "nand", "nor", "not", "buf", "xor", "xnor"}

ZERO_KEYWORDS = {
    "always",
    "always_comb",
    "always_ff",
    "always_latch",
    "automatic",
    "assign",
    "begin",
    "bit",
    "byte",
    "else",
    "end",
    "endcase",
    "endfunction",
    "endgenerate",
    "endmodule",
    "endtask",
    "enum",
    "for",
    "function",
    "generate",
    "genvar",
    "initial",
    "input",
    "int",
    "integer",
    "localparam",
    "logic",
    "longint",
    "macromodule",
    "module",
    "output",
    "parameter",
    "reg",
    "return",
    "shortint",
    "signed",
    "struct",
    "task",
    "typedef",
    "union",
    "unsigned",
    "wire",
}

DECL_KEYWORDS = {"input", "output", "wire", "reg", "integer", "parameter", "localparam", "logic", "bit"}
CASE_KEYWORDS = {"case", "casex", "casez"}
CONTROL_START = {";", "begin", "end", "endmodule", "module"}

MULTI_OPS = [
    "!==",
    "===",
    "<<<",
    ">>>",
    "**",
    ">=",
    "<=",
    "==",
    "!=",
    "&&",
    "||",
    "<<",
    ">>",
    "~&",
    "~|",
    "^~",
    "~^",
]

SINGLE_OPS = set("{}[]()+-*/%><!~&|^?:=,;@#.")
MULTI_BY_FIRST: Dict[str, List[str]] = {}
for _op in sorted(MULTI_OPS, key=len, reverse=True):
    MULTI_BY_FIRST.setdefault(_op[0], []).append(_op)
IDENT_START = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_\\$")
IDENT_BODY = IDENT_START | set("0123456789")
BASED_LITERAL_BODY = set("0123456789abcdefABCDEF_xXzZ?")
DEFAULT_SYNTAX_COST_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "syntax_cost.csv"
)
_OPERATOR_COSTS: Optional[Dict[str, int]] = None
_OPERATOR_COST_CSV = DEFAULT_SYNTAX_COST_CSV


@dataclass
class Module:
    name: str
    tokens: List[str]
    text: str
    widths: Dict[str, int]


def load_operator_costs(path: str = DEFAULT_SYNTAX_COST_CSV) -> Dict[str, int]:
    costs: Dict[str, int] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("key") or "").strip()
            if not key:
                continue
            try:
                costs[key] = int(row["cost"])
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{path}: invalid cost row for {key!r}") from exc
    return costs


def set_operator_cost_csv(path: str) -> None:
    global _OPERATOR_COSTS, _OPERATOR_COST_CSV
    _OPERATOR_COST_CSV = path
    _OPERATOR_COSTS = None


def operator_costs() -> Dict[str, int]:
    global _OPERATOR_COSTS
    if _OPERATOR_COSTS is None:
        _OPERATOR_COSTS = load_operator_costs(_OPERATOR_COST_CSV)
    return _OPERATOR_COSTS


def operator_cost(name: str) -> int:
    costs = operator_costs()
    if name not in costs:
        raise KeyError(f"operator cost for {name!r} is missing from {_OPERATOR_COST_CSV}")
    return costs[name]


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def primitive_only_gate_count(text: str) -> Optional[int]:
    """Fast path for counting flattened gate-level netlists made only of primitives."""
    clean = strip_comments(text)
    count = 0
    for stmt in clean.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        if stmt == "endmodule":
            continue
        first_match = re.match(r"([A-Za-z_\\$][A-Za-z0-9_\\$]*)", stmt)
        if not first_match:
            return None
        first = first_match.group(1)
        if first in {"module", "input", "output", "wire", "reg", "integer", "parameter"}:
            continue
        if first in PRIMITIVES:
            count += max(1, stmt.count("("))
            continue
        return None
    return count


def primitive_only_cost(text: str) -> Optional[int]:
    gate_count = primitive_only_gate_count(text)
    if gate_count is None:
        return None
    return gate_count * operator_cost("primitive_gate")


def tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue

        if c in IDENT_START:
            j = i + 1
            while j < n and text[j] in IDENT_BODY:
                j += 1
            tokens.append(text[i:j])
            i = j
            continue

        if c.isdigit():
            j = i + 1
            while j < n and text[j].isdigit():
                j += 1
            if j < n and text[j] == "'":
                k = j + 1
                if k < n and text[k] in "sS":
                    k += 1
                if k < n and text[k] in "bBoOdDhH":
                    k += 1
                    while k < n and text[k] in BASED_LITERAL_BODY:
                        k += 1
                    tokens.append(text[i:k])
                    i = k
                    continue
            tokens.append(text[i:j])
            i = j
            continue

        matched = False
        for op in MULTI_BY_FIRST.get(c, ()):
            if text.startswith(op, i):
                tokens.append(op)
                i += len(op)
                matched = True
                break
        if matched:
            continue

        tokens.append(c)
        i += 1
    return tokens


def parse_range_width(msb: str, lsb: str) -> Optional[int]:
    try:
        return abs(int(msb) - int(lsb)) + 1
    except ValueError:
        return None


def parse_decl_widths(text: str) -> Dict[str, int]:
    widths: Dict[str, int] = {}
    statements = [s.strip() for s in text.split(";")]
    for stmt in statements:
        m = re.match(
            r"^(input|output|wire|reg)\b\s*(?:signed|unsigned)?\s*"
            r"(?:\[\s*([0-9]+)\s*:\s*([0-9]+)\s*\])?\s*(.*)$",
            stmt,
            flags=re.S,
        )
        if not m:
            continue
        width = 1
        if m.group(2) is not None and m.group(3) is not None:
            parsed = parse_range_width(m.group(2), m.group(3))
            if parsed:
                width = parsed

        names = m.group(4)
        for part in names.split(","):
            part = part.split("=", 1)[0].strip()
            name = re.match(r"([A-Za-z_\\$][A-Za-z0-9_\\$]*)", part)
            if name:
                widths[name.group(1)] = width
    return widths


def parse_modules(text: str) -> Dict[str, Module]:
    clean = strip_comments(text)
    matches = list(re.finditer(r"\bmodule\s+([A-Za-z_\\$][A-Za-z0-9_\\$]*)\b", clean))
    modules: Dict[str, Module] = {}
    for match in matches:
        name = match.group(1)
        end = re.search(r"\bendmodule\b", clean[match.end() :])
        if not end:
            raise ValueError(f"module {name}: missing endmodule")
        start_pos = match.start()
        end_pos = match.end() + end.end()
        module_text = clean[start_pos:end_pos]
        modules[name] = Module(
            name=name,
            tokens=tokenize(module_text),
            text=module_text,
            widths=parse_decl_widths(module_text),
        )
    return modules


def find_matching(tokens: Sequence[str], start: int, left: str, right: str) -> int:
    depth = 0
    for i in range(start, len(tokens)):
        if tokens[i] == left:
            depth += 1
        elif tokens[i] == right:
            depth -= 1
            if depth == 0:
                return i
    return len(tokens) - 1


def make_skip_mask(tokens: Sequence[str]) -> List[bool]:
    skip = [False] * len(tokens)

    # Skip the module declaration header.
    if tokens and tokens[0] == "module":
        for i, tok in enumerate(tokens):
            skip[i] = True
            if tok == ";":
                break

    # Skip event controls, especially always @(*) where * is not arithmetic.
    i = 0
    while i < len(tokens):
        if tokens[i] == "@":
            skip[i] = True
            if i + 1 < len(tokens) and tokens[i + 1] == "(":
                end = find_matching(tokens, i + 1, "(", ")")
                for j in range(i + 1, end + 1):
                    skip[j] = True
                i = end + 1
                continue
        i += 1

    # Skip declaration prefixes/ranges. Initializer expressions after '=' still count.
    stmt_start = 0
    i = 0
    while i < len(tokens):
        if tokens[i] == ";":
            stmt_start = i + 1
        if tokens[i] in DECL_KEYWORDS and all(t in CONTROL_START for t in tokens[stmt_start:i]):
            j = i
            while j < len(tokens) and tokens[j] != ";":
                if tokens[j] == "=":
                    break
                skip[j] = True
                j += 1
            i = j
            continue
        i += 1

    return skip


def is_identifier(tok: str) -> bool:
    return bool(re.match(r"^[A-Za-z_\\$][A-Za-z0-9_\\$]*$", tok))


def previous_significant(tokens: Sequence[str], skip: Sequence[bool], i: int) -> Optional[str]:
    j = i - 1
    while j >= 0:
        if not skip[j] and tokens[j] not in {",", "begin", "end"}:
            return tokens[j]
        j -= 1
    return None


def next_significant(tokens: Sequence[str], skip: Sequence[bool], i: int) -> Optional[str]:
    j = i + 1
    while j < len(tokens):
        if not skip[j] and tokens[j] not in {","}:
            return tokens[j]
        j += 1
    return None


def is_unary_context(prev: Optional[str]) -> bool:
    if prev is None:
        return True
    return prev in {
        "(",
        "{",
        "[",
        "?",
        ":",
        "=",
        "==",
        "!=",
        "===",
        "!==",
        "&&",
        "||",
        "+",
        "-",
        "*",
        "/",
        "%",
        "**",
        ">",
        ">=",
        "<",
        "<=",
        "<<",
        ">>",
        "<<<",
        ">>>",
        "!",
        "~",
        "&",
        "|",
        "^",
        "~&",
        "~|",
        "~^",
        "^~",
        ";",
        "begin",
        "if",
        "case",
        "casex",
        "casez",
    }


def token_width(tok: Optional[str], widths: Dict[str, int]) -> int:
    if tok is None:
        return 1
    literal = re.match(r"^(\d+)'", tok)
    if literal:
        return int(literal.group(1))
    if tok.isdigit():
        return 32
    return widths.get(tok, 1)


def operand_width_left(tokens: Sequence[str], skip: Sequence[bool], i: int, widths: Dict[str, int]) -> int:
    j = i - 1
    while j >= 0 and (skip[j] or tokens[j] in {")", "]"}):
        if tokens[j] == "]":
            k = j - 1
            colon = False
            nums: List[str] = []
            while k >= 0 and tokens[k] != "[":
                if tokens[k] == ":":
                    colon = True
                elif tokens[k].isdigit():
                    nums.append(tokens[k])
                k -= 1
            if colon and len(nums) >= 2:
                parsed = parse_range_width(nums[-1], nums[0])
                if parsed:
                    return parsed
            return 1
        j -= 1
    return token_width(tokens[j] if j >= 0 else None, widths)


def operand_width_right(tokens: Sequence[str], skip: Sequence[bool], i: int, widths: Dict[str, int]) -> int:
    j = i + 1
    while j < len(tokens) and skip[j]:
        j += 1
    return token_width(tokens[j] if j < len(tokens) else None, widths)


def is_assignment_le(tokens: Sequence[str], skip: Sequence[bool], i: int) -> bool:
    """Return True when '<=' is a nonblocking assignment, not relational <=."""
    j = i - 1
    while j >= 0 and skip[j]:
        j -= 1
    if j < 0 or not (is_identifier(tokens[j]) or tokens[j] == "]"):
        return False

    paren_depth = bracket_depth = brace_depth = 0
    k = i - 1
    saw_lvalue = False
    while k >= 0:
        tok = tokens[k]
        if skip[k]:
            k -= 1
            continue
        if tok == ")":
            paren_depth += 1
        elif tok == "(":
            if paren_depth == 0:
                return False
            paren_depth -= 1
        elif tok == "]":
            bracket_depth += 1
        elif tok == "[":
            bracket_depth -= 1
        elif tok == "}":
            brace_depth += 1
        elif tok == "{":
            brace_depth -= 1
        elif paren_depth == bracket_depth == brace_depth == 0:
            if tok in {";", "begin", "end", ":"}:
                return saw_lvalue
            if tok in {"if", "case", "casex", "casez", "(", "?", "=", ","}:
                return False
            if is_identifier(tok):
                saw_lvalue = True
            elif tok not in {"]"}:
                return False
        k -= 1
    return saw_lvalue


def concat_cost(tokens: Sequence[str], skip: Sequence[bool], start: int) -> Tuple[int, int]:
    end = find_matching(tokens, start, "{", "}")
    depth = 0
    items = 1
    has_token = False
    for i in range(start + 1, end):
        if skip[i]:
            continue
        tok = tokens[i]
        if tok in {"{", "(", "["}:
            depth += 1
        elif tok in {"}", ")", "]"}:
            depth -= 1
        elif tok == "," and depth == 0:
            items += 1
        else:
            has_token = True
    return (items if has_token else 0), end


def case_item_count(tokens: Sequence[str], skip: Sequence[bool]) -> int:
    count = 0
    i = 0
    while i < len(tokens):
        if tokens[i] not in CASE_KEYWORDS or skip[i]:
            i += 1
            continue
        end = i + 1
        depth = 0
        while end < len(tokens):
            tok = tokens[end]
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
            end += 1

        j = end
        paren = bracket = brace = ternary = 0
        while j < len(tokens) and tokens[j] != "endcase":
            tok = tokens[j]
            if skip[j]:
                j += 1
                continue
            if tok == "(":
                paren += 1
            elif tok == ")":
                paren -= 1
            elif tok == "[":
                bracket += 1
            elif tok == "]":
                bracket -= 1
            elif tok == "{":
                brace += 1
            elif tok == "}":
                brace -= 1
            elif tok == "?":
                ternary += 1
            elif tok == ":" and paren == bracket == brace == 0:
                if ternary:
                    ternary -= 1
                else:
                    k = j - 1
                    while k > end and skip[k]:
                        k -= 1
                    if k >= end and tokens[k] != "default":
                        count += 1
            j += 1
        i = j + 1
    return count


def split_statements(tokens: Sequence[str]) -> Iterable[List[str]]:
    start = 0
    paren = bracket = brace = 0
    for i, tok in enumerate(tokens):
        if tok == "(":
            paren += 1
        elif tok == ")":
            paren -= 1
        elif tok == "[":
            bracket += 1
        elif tok == "]":
            bracket -= 1
        elif tok == "{":
            brace += 1
        elif tok == "}":
            brace -= 1
        elif tok == ";" and paren == bracket == brace == 0:
            yield list(tokens[start : i + 1])
            start = i + 1


def primitive_instances(stmt: Sequence[str]) -> int:
    useful = [t for t in stmt if t not in {";", ","}]
    if not useful or useful[0] not in PRIMITIVES:
        return 0
    paren_depth = 0
    instances = 0
    for tok in stmt[1:]:
        if tok == "(":
            if paren_depth == 0:
                instances += 1
            paren_depth += 1
        elif tok == ")":
            paren_depth -= 1
    return max(instances, 1)


def submodule_instances(tokens: Sequence[str], module_names: Iterable[str]) -> List[str]:
    known = set(module_names)
    insts: List[str] = []
    ignored = DECL_KEYWORDS | ZERO_KEYWORDS | PRIMITIVES | CASE_KEYWORDS | {"if", "default"}
    for stmt in split_statements(tokens):
        useful = [t for t in stmt if t not in {";", ","}]
        if len(useful) < 3:
            continue
        first = useful[0]
        if first in ignored or first not in known:
            continue
        paren_depth = 0
        count = 0
        for tok in useful[1:]:
            if tok == "(":
                if paren_depth == 0:
                    count += 1
                paren_depth += 1
            elif tok == ")":
                paren_depth -= 1
        insts.extend([first] * max(count, 1))
    return insts


def direct_module_cost(module: Module) -> Tuple[int, Dict[str, int]]:
    tokens = module.tokens
    skip = make_skip_mask(tokens)
    detail: Dict[str, int] = {}

    def add(name: str, count: int = 1) -> None:
        if count:
            detail[name] = detail.get(name, 0) + count * operator_cost(name)

    add("case_items", case_item_count(tokens, skip))

    for stmt in split_statements(tokens):
        add("primitive_gate", primitive_instances(stmt))

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if skip[i]:
            i += 1
            continue

        if tok == "if":
            add("if")
        elif tok in CASE_KEYWORDS:
            pass
        elif tok == "{":
            cost, end = concat_cost(tokens, skip, i)
            add("concat", cost)
            i = end
        elif tok == "[":
            add("select")
        elif tok == "-":
            if is_unary_context(previous_significant(tokens, skip, i)):
                add("unary_-")
            else:
                add("-")
        elif tok in {"+", "/", "%", "**"}:
            add(tok)
        elif tok == "*":
            add("*")
        elif tok in {">", ">=", "<"}:
            add(tok)
        elif tok == "<=":
            if not is_assignment_le(tokens, skip, i):
                add("<=")
        elif tok in {"==", "!=", "===", "!==", "!", "&&", "||"}:
            add(tok)
        elif tok in {"<<", ">>", "<<<", ">>>"}:
            add(tok)
        elif tok == "?":
            add("?:")
        elif tok in {"~&", "~|"}:
            add(tok)
        elif tok in {"~^", "^~"}:
            prev = previous_significant(tokens, skip, i)
            if is_unary_context(prev):
                add("reduction_xnor")
            else:
                width = max(
                    operand_width_left(tokens, skip, i, module.widths),
                    operand_width_right(tokens, skip, i, module.widths),
                )
                add(tok, width)
        elif tok in {"~", "&", "|", "^"}:
            prev = previous_significant(tokens, skip, i)
            if tok == "~":
                add(tok, operand_width_right(tokens, skip, i, module.widths))
            elif is_unary_context(prev):
                add(f"reduction_{tok}")
            else:
                width = max(
                    operand_width_left(tokens, skip, i, module.widths),
                    operand_width_right(tokens, skip, i, module.widths),
                )
                add(tok, width)
        i += 1

    return sum(detail.values()), detail


def module_costs(modules: Dict[str, Module]) -> Tuple[Dict[str, int], Dict[str, Dict[str, int]]]:
    direct: Dict[str, int] = {}
    details: Dict[str, Dict[str, int]] = {}
    for name, module in modules.items():
        direct[name], details[name] = direct_module_cost(module)

    visiting: set[str] = set()
    memo: Dict[str, int] = {}

    def resolve(name: str) -> int:
        if name in memo:
            return memo[name]
        if name in visiting:
            raise ValueError(f"recursive module instantiation involving {name}")
        visiting.add(name)
        total = direct[name]
        for sub in submodule_instances(modules[name].tokens, modules.keys()):
            total += resolve(sub)
            details[name][f"inst:{sub}"] = details[name].get(f"inst:{sub}", 0) + resolve(sub)
        visiting.remove(name)
        memo[name] = total
        return total

    return {name: resolve(name) for name in modules}, details


def evaluate_rtl(path: str) -> Tuple[int, Dict[str, int], Dict[str, int]]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    primitive_cost = primitive_only_cost(text)
    if primitive_cost is not None:
        return primitive_cost, {"top": primitive_cost}, {"primitive_gate": primitive_cost}
    modules = parse_modules(text)
    if "top" not in modules:
        raise ValueError(f"{path}: no top module")
    costs, details = module_costs(modules)
    return costs["top"], costs, details["top"]


def count_primitive_gates(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    primitive_count = primitive_only_gate_count(text)
    if primitive_count is not None:
        return primitive_count
    tokens = tokenize(strip_comments(text))
    count = 0
    for stmt in split_statements(tokens):
        count += primitive_instances(stmt)
    return count


def paired_input_path(output_path: str, input_dir: Optional[str]) -> Optional[str]:
    if not input_dir:
        return None
    base = os.path.splitext(os.path.basename(output_path))[0]
    candidate = os.path.join(input_dir, base, "top_primitive.v")
    return candidate if os.path.exists(candidate) else None


def evaluate_paths(paths: Sequence[str], input_dir: Optional[str]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for path in sorted(paths):
        cost, module_cost_map, detail = evaluate_rtl(path)
        input_path = paired_input_path(path, input_dir)
        gate_count = count_primitive_gates(input_path) if input_path else None
        reduction_rate = None
        passed_70 = None
        if gate_count:
            reduction_rate = (1.0 - cost / gate_count) * 100.0
            passed_70 = reduction_rate >= 70.0
        rows.append(
            {
                "case": os.path.splitext(os.path.basename(path))[0],
                "rtl": path,
                "input": input_path,
                "cost": cost,
                "gate_count": gate_count,
                "reduction_rate": reduction_rate,
                "passed_70": passed_70,
                "module_costs": module_cost_map,
                "detail": detail,
            }
        )
    return rows


def print_table(rows: Sequence[Dict[str, object]], show_detail: bool = False) -> None:
    has_gate = any(row["gate_count"] is not None for row in rows)
    if has_gate:
        print(f"{'case':<8} {'cost':>6} {'gates':>8} {'reduction':>10} {'>=70%':>7}")
        print("-" * 43)
    else:
        print(f"{'case':<8} {'cost':>6}")
        print("-" * 15)

    total_cost = 0
    total_gates = 0
    for row in rows:
        total_cost += int(row["cost"])
        if row["gate_count"] is not None:
            total_gates += int(row["gate_count"])
        if has_gate:
            reduction = row["reduction_rate"]
            reduction_s = "-" if reduction is None else f"{reduction:9.2f}%"
            passed = "-" if row["passed_70"] is None else ("yes" if row["passed_70"] else "no")
            print(
                f"{row['case']:<8} {int(row['cost']):>6} "
                f"{str(row['gate_count'] or '-'):>8} {reduction_s:>10} {passed:>7}"
            )
        else:
            print(f"{row['case']:<8} {int(row['cost']):>6}")
        if show_detail:
            detail = row["detail"]
            if isinstance(detail, dict):
                parts = ", ".join(f"{k}={v}" for k, v in sorted(detail.items()))
                print(f"  {parts}")

    print("-" * (43 if has_gate else 15))
    if has_gate and total_gates:
        total_reduction = (1.0 - total_cost / total_gates) * 100.0
        print(f"{'TOTAL':<8} {total_cost:>6} {total_gates:>8} {total_reduction:9.2f}%")
    else:
        print(f"{'TOTAL':<8} {total_cost:>6}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="RTL Verilog files to evaluate")
    parser.add_argument(
        "--output-dir",
        default="output",
        help="directory containing RTL outputs when files are not provided",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help=(
            "optional directory containing <case>/top_primitive.v for original "
            "gate counts and reduction-rate reporting"
        ),
    )
    parser.add_argument(
        "--cost-csv",
        default=DEFAULT_SYNTAX_COST_CSV,
        help="CSV file with key,cost columns; defaults to syntax_cost.csv",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--detail", action="store_true", help="show per-operator detail")
    args = parser.parse_args(argv)

    set_operator_cost_csv(args.cost_csv)

    paths = args.files or sorted(glob.glob(os.path.join(args.output_dir, "*.v")))
    if not paths:
        raise SystemExit("no RTL files found")

    rows = evaluate_paths(paths, args.input_dir)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print_table(rows, show_detail=args.detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

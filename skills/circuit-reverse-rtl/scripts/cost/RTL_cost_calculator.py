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


class DeclaredWidths(dict):
    """Legacy widths plus packed/unpacked shape for direct selected operands."""
    def __init__(self):
        super().__init__()
        self.shapes = {}


def constant_dimension(tokens: Sequence[str]) -> Optional[int]:
    # Deliberately restricted: a full Verilog constant/type evaluator is out
    # of scope. Unknown dimensions remain explicit instead of becoming bit1.
    if len(tokens) == 3 and tokens[1] == ":" and tokens[0].isdigit() and tokens[2].isdigit():
        return abs(int(tokens[0]) - int(tokens[2])) + 1
    return None


def bracket_tokens(tokens: Sequence[str], start: int) -> Tuple[List[str], int]:
    depth = 1
    index = start + 1
    while index < len(tokens) and depth:
        if tokens[index] == "[":
            depth += 1
        elif tokens[index] == "]":
            depth -= 1
        if depth:
            index += 1
    if depth:
        raise ValueError("cost width: incomplete selection/declaration")
    return list(tokens[start + 1:index]), index + 1


def shape_width(packed: Sequence[Optional[int]]) -> Optional[int]:
    width = 1
    for dimension in packed:
        if dimension is None:
            return None
        width *= dimension
    return width


def parse_decl_widths(text: str) -> Dict[str, int]:
    widths = DeclaredWidths()
    tokens = tokenize(strip_comments(text))
    types = {"input", "output", "wire", "reg", "logic", "integer", "int", "byte", "shortint", "longint"}
    index = 0
    while index < len(tokens):
        if tokens[index] not in types:
            index += 1
            continue
        declared_type = tokens[index]
        index += 1
        while index < len(tokens) and tokens[index] in types | {"signed", "unsigned"}:
            if tokens[index] in {"integer", "int", "byte", "shortint", "longint"}:
                declared_type = tokens[index]
            index += 1
        packed = []
        while index < len(tokens) and tokens[index] == "[":
            dimensions, index = bracket_tokens(tokens, index)
            packed.append(constant_dimension(dimensions))
        if not packed and declared_type in {"integer", "int", "byte", "shortint", "longint"}:
            packed = [{"integer": 32, "int": 32, "byte": 8, "shortint": 16, "longint": 64}[declared_type]]
        while index < len(tokens) and re.fullmatch(r"[A-Za-z_$][\w$]*", tokens[index]) and tokens[index] not in types:
            name = tokens[index]
            index += 1
            unpacked = 0
            while index < len(tokens) and tokens[index] == "[":
                _, index = bracket_tokens(tokens, index)
                unpacked += 1
            widths.shapes[name] = (tuple(packed), unpacked)
            width = shape_width(packed)
            if width is not None:
                widths[name] = width
            depth = 0
            while index < len(tokens):
                token = tokens[index]
                if token in {",", ";", ")"} and depth == 0:
                    break
                if token in {"(", "[", "{"}:
                    depth += 1
                elif token in {")", "]", "}"}:
                    depth -= 1
                index += 1
            if index < len(tokens) and tokens[index] == ",":
                index += 1
                if index < len(tokens) and tokens[index] in types:
                    break
                continue
            break
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


def selected_identifier_width(tokens: Sequence[str], start: int, widths: Dict[str, int]) -> int:
    name = tokens[start]
    shapes = getattr(widths, "shapes", {})
    if name not in shapes and name not in widths:
        raise ValueError("cost width: selected identifier has undeclared or unsupported type")
    packed, unpacked = shapes[name] if name in shapes else ((widths[name],), 0)
    packed = list(packed)
    index = start + 1
    while index < len(tokens) and tokens[index] == "[":
        selection, index = bracket_tokens(tokens, index)
        has_colon = ":" in selection
        if unpacked:
            if has_colon:
                raise ValueError("cost width: unpacked array slice is unsupported")
            unpacked -= 1
            continue
        if not packed:
            # A scalar bit-select is itself scalar.
            packed = [1]
        if not has_colon:
            packed.pop(0)
        else:
            width = constant_dimension(selection)
            # Indexed part-select: base +: W or base -: W, fixed decimal W.
            if width is None and len(selection) >= 3 and selection[-2] == ":" and selection[-3] in {"+", "-"} and selection[-1].isdigit():
                width = int(selection[-1])
            if width is None or width < 1:
                raise ValueError("cost width: selected packed width is not a supported constant")
            packed[0] = width
    if unpacked:
        raise ValueError("cost width: an unindexed unpacked array operand is unsupported")
    width = shape_width(packed)
    if width is None:
        raise ValueError("cost width: selected word has unknown packed dimension")
    return width


def operand_width_left(tokens: Sequence[str], skip: Sequence[bool], i: int, widths: Dict[str, int]) -> int:
    j = i - 1
    while j >= 0 and (skip[j] or tokens[j] == ")"):
        j -= 1
    if j >= 0 and tokens[j] == "]":
        # Walk all selections back to their declared signal, including nested
        # index expressions; array elements can still be whole packed words.
        start = j
        while start >= 0 and tokens[start] == "]":
            depth = 1
            start -= 1
            while start >= 0 and depth:
                if tokens[start] == "]":
                    depth += 1
                elif tokens[start] == "[":
                    depth -= 1
                start -= 1
        if start >= 0 and re.fullmatch(r"[A-Za-z_$][\w$]*", tokens[start]):
            return selected_identifier_width(tokens, start, widths)
        return 1
    return token_width(tokens[j] if j >= 0 else None, widths)


def operand_width_right(tokens: Sequence[str], skip: Sequence[bool], i: int, widths: Dict[str, int]) -> int:
    j = i + 1
    while j < len(tokens) and skip[j]:
        j += 1
    if j < len(tokens) and re.fullmatch(r"[A-Za-z_$][\w$]*", tokens[j]):
        if j + 1 < len(tokens) and tokens[j + 1] == "[":
            return selected_identifier_width(tokens, j, widths)
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
            cost, _ = concat_cost(tokens, skip, i)
            add("concat", cost)
            # Concatenation is an expression container, not a free operator
            # boundary. Continue traversing its contents so nested arithmetic,
            # comparisons, selections and concatenations are charged as usual.
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

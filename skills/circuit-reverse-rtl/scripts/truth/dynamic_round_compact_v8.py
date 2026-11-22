"""Fail-closed factoring of a positively bounded dynamic signed-64 RNE.

This module does not inspect input filenames, truth tables, or cost results.
It accepts only one combinational procedural body, completely parses that
body, and preserves both shift-defining branches and every rounding stage.
Call before signed-operator factoring. Unsupported syntax returns the input.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


RNE64_HELPER = '''  // Exact signed round-to-nearest-even; shift is between 1 and 63.
  function signed [63:0] semantic_rne64;
    input signed [63:0] value;
    input [5:0] shift;
    input signed [64:0] bias;
    reg signed [64:0] extended;
    begin
      extended = value;
      extended = extended + bias;
      extended = extended + value[shift];
      semantic_rne64 = extended >>> shift;
    end
  endfunction

'''

_TOKEN = re.compile(r"\s+|\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|\d+|"
                    r"[A-Za-z_$][A-Za-z0-9_$]*|>>>|<<<|>>|<<|===|!==|"
                    r"==|!=|<=|>=|&&|\|\||\*\*|[()\[\]{},;:?=+*/%~!&|^<>-]")
_PREC = {'||': 1, '&&': 2, '|': 3, '^': 4, '&': 5,
         '==': 6, '!=': 6, '===': 6, '!==': 6,
         '<': 7, '>': 7, '<=': 7, '>=': 7,
         '<<': 8, '>>': 8, '<<<': 8, '>>>': 8,
         '+': 9, '-': 9, '*': 10, '/': 10, '%': 10, '**': 11}


@dataclass
class Statement:
    kind: str
    start: int
    end: int
    lhs: tuple | None = None
    rhs: tuple | None = None
    condition: tuple | None = None
    children: tuple = ()


class _Parser:
    def __init__(self, text: str):
        self.tokens = []
        pos = 0
        for match in _TOKEN.finditer(text):
            if match.start() != pos:
                raise ValueError('unsupported lexical syntax')
            pos = match.end()
            if not match[0].isspace():
                self.tokens.append((match[0], match.start(), match.end()))
        if pos != len(text):
            raise ValueError('unconsumed lexical syntax')
        self.i = 0

    def peek(self):
        return self.tokens[self.i][0] if self.i < len(self.tokens) else None

    def pop(self, expected=None):
        if self.i == len(self.tokens):
            raise ValueError('unexpected end')
        token = self.tokens[self.i]
        if expected is not None and token[0] != expected:
            raise ValueError('unexpected token')
        self.i += 1
        return token

    def expression(self, minimum=0):
        token = self.pop()[0]
        if token in ('+', '-', '~', '!', '&', '|', '^'):
            lhs = ('unary', token, self.expression(12))
        elif token == '(':
            lhs = self.expression()
            self.pop(')')
        elif token == '{':
            items = [self.expression()]
            while self.peek() == ',':
                self.pop(',')
                items.append(self.expression())
            self.pop('}')
            lhs = ('concat', *items)
        elif re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', token):
            if token in ('begin', 'end', 'if', 'else', 'for', 'while', 'repeat', 'case'):
                raise ValueError('keyword used as expression')
            lhs = ('id', token)
        elif re.fullmatch(r"\d+(?:'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+)?", token):
            lhs = ('number', token)
        else:
            raise ValueError('unsupported primary')
        while self.peek() in ('(', '['):
            if self.peek() == '(':
                if lhs[0] != 'id':
                    raise ValueError('unsupported callee')
                self.pop('(')
                args = []
                if self.peek() != ')':
                    args.append(self.expression())
                    while self.peek() == ',':
                        self.pop(',')
                        args.append(self.expression())
                self.pop(')')
                lhs = ('call', lhs[1], *args)
            else:
                self.pop('[')
                index = self.expression()
                if self.peek() == ':':
                    self.pop(':')
                    low = self.expression()
                    lhs = ('slice', lhs, index, low)
                else:
                    lhs = ('select', lhs, index)
                self.pop(']')
        while self.peek() in _PREC and _PREC[self.peek()] >= minimum:
            operator = self.pop()[0]
            precedence = _PREC[operator]
            rhs = self.expression(precedence if operator == '**' else precedence + 1)
            lhs = ('binary', operator, lhs, rhs)
        if minimum == 0 and self.peek() == '?':
            self.pop('?')
            yes = self.expression()
            self.pop(':')
            lhs = ('conditional', lhs, yes, self.expression())
        return lhs

    def statement(self):
        start = self.tokens[self.i][1]
        if self.peek() == 'begin':
            self.pop('begin')
            children = []
            while self.peek() != 'end':
                children.append(self.statement())
            end = self.pop('end')[2]
            return Statement('block', start, end, children=tuple(children))
        if self.peek() == 'if':
            self.pop('if'); self.pop('(')
            condition = self.expression()
            self.pop(')')
            children = [self.statement()]
            if self.peek() == 'else':
                self.pop('else')
                children.append(self.statement())
            return Statement('if', start, children[-1].end,
                             condition=condition, children=tuple(children))
        lhs = self.expression(12)
        if lhs[0] not in ('id', 'select', 'slice'):
            raise ValueError('unsupported assignment target')
        self.pop('=')
        rhs = self.expression()
        end = self.pop(';')[2]
        return Statement('assign', start, end, lhs=lhs, rhs=rhs)


def _expr(text):
    parser = _Parser(text)
    result = parser.expression()
    if parser.peek() is not None:
        raise ValueError('expression not fully consumed')
    return result


def _walk(statement):
    yield statement
    for child in statement.children:
        yield from _walk(child)


def _names(expression):
    if expression is None:
        return set()
    result = {expression[1]} if expression[0] == 'id' else set()
    for part in expression[1:]:
        if isinstance(part, tuple):
            result.update(_names(part))
    return result


def _branch_bounds(statement, shift, scratch):
    if statement.kind != 'if' or len(statement.children) != 2:
        return False
    for branch in statement.children:
        if branch.kind != 'block' or not branch.children:
            return False
        definitions = []
        for item in branch.children:
            if item.kind != 'assign' or item.lhs[0] != 'id':
                return False
            if item.lhs == ('id', shift):
                if item.rhs[0] != 'number' or not item.rhs[1].isdigit():
                    return False
                definitions.append(int(item.rhs[1]))
            elif item.lhs[1] in scratch:
                return False
            if shift in _names(item.rhs) or scratch & _names(item.rhs):
                return False
        if (len(definitions) != 1 or not 1 <= definitions[0] <= 63 or
                branch.children[-1].lhs != ('id', shift)):
            return False
    return True


def share_dynamic_round_to_even(rtl: str) -> str:
    """Replace only exact dynamic RNE blocks with proven positive shifts.

    Accepted source/destination/remainder/half are distinct signed-64 regs;
    shift is an integer. Every candidate has immediately preceding complete
    if/else blocks with one constant shift definition per branch. Scratch
    reads outside accepted RNE blocks, unknown helper bodies, procedural
    syntax, comments inside matched statements, or macros fail closed.
    """
    marker = '  always @(*) begin'
    if rtl.count(marker) != 1 or '`' in rtl or '/*' in rtl:
        return rtl
    # Line comments retain offsets. A replacement must not erase a comment.
    code = re.sub(r'//[^\n]*', lambda m: ' ' * len(m[0]), rtl)
    header, tail = code.split(marker, 1)
    offset = len(header) + len('  always @(*) ')
    body = code[offset:]
    try:
        parser = _Parser(body)
        top = parser.statement()
        parser.pop('endmodule')
        if parser.peek() is not None:
            return rtl
    except (ValueError, IndexError):
        return rtl
    # Reject multiple procedural regions and unsupported header scopes.
    if re.search(r'\b(always|initial|task)\b', header):
        return rtl
    declaration_scope = re.sub(r'\bfunction\b.*?\bendfunction\b', '', header, flags=re.S)
    signed64, integers = set(), set()
    for declaration in re.finditer(r'\breg\s+signed\s*\[63:0\]\s*([^;]+);', declaration_scope):
        if all(re.fullmatch(r'\s*[A-Za-z_]\w*\s*', name) for name in declaration[1].split(',')):
            signed64.update(name.strip() for name in declaration[1].split(','))
    for declaration in re.finditer(r'\binteger\s+([^;]+);', declaration_scope):
        if all(re.fullmatch(r'\s*[A-Za-z_]\w*\s*', name) for name in declaration[1].split(',')):
            integers.update(name.strip() for name in declaration[1].split(','))
    helper_definitions = list(re.finditer(r'\bfunction\b.*?\bendfunction\b', header, flags=re.S))
    known = [m for m in helper_definitions if re.search(r'\bsemantic_rne64\b', m[0])]
    if known:
        # Reuse only the exact canonical helper, including full intermediate width.
        canonical = re.sub(r'\s+', '', re.sub(r'//[^\n]*', '', RNE64_HELPER))
        if len(known) != 1 or re.sub(r'\s+', '', known[0][0]) != canonical:
            return rtl
    elif re.search(r'\bsemantic_rne64\b', code):
        return rtl
    candidates = []
    for group in _walk(top):
        if group.kind != 'block':
            continue
        statements = group.children
        for i in range(1, len(statements) - 3):
            rounded, remainder, half, increment = statements[i:i+4]
            if any(s.kind != 'assign' or s.lhs[0] != 'id' for s in (rounded, remainder, half)):
                continue
            dst, rem, half_name = rounded.lhs[1], remainder.lhs[1], half.lhs[1]
            rhs = rounded.rhs
            if (rhs[:2] != ('binary', '>>>') or rhs[2][0] != 'id' or rhs[3][0] != 'id'):
                continue
            src, shift = rhs[2][1], rhs[3][1]
            if len({dst, src, rem, half_name, shift}) != 5:
                continue
            if not {dst, src, rem, half_name} <= signed64 or shift not in integers:
                continue
            integer_free_scope = re.sub(r'\binteger\s+[^;]+;', '', declaration_scope)
            if re.search(r'\b' + re.escape(shift) + r'\b', integer_free_scope):
                continue
            if remainder.rhs != _expr(f'{src} - ({dst} <<< {shift})'):
                continue
            if half.rhs != _expr(f"64'sd1 <<< ({shift} - 1)"):
                continue
            if increment.kind != 'if' or len(increment.children) != 1:
                continue
            if increment.condition != _expr(f'({rem} > {half_name}) || (({rem} == {half_name}) && {dst}[0])'):
                continue
            inc = increment.children[0]
            if (inc.kind != 'assign' or inc.lhs != rounded.lhs or
                    inc.rhs != _expr(f'{dst} + 1')):
                continue
            if not _branch_bounds(statements[i-1], shift, {rem, half_name}):
                continue
            raw = rtl[offset + rounded.start:offset + increment.end]
            if '//' in raw:
                continue
            # A helper or header initializer must not observe scratch values.
            scope_without_declarations = re.sub(r'\breg\s+signed\s*\[63:0\]\s*[^;]+;', '', header)
            if re.search(r'\b(' + re.escape(rem) + '|' + re.escape(half_name) + r')\b', scope_without_declarations):
                continue
            candidates.append((rounded.start, increment.end, dst, src, shift, rem, half_name))
    if not candidates:
        return rtl
    # No scratch read or mutation is permitted beyond accepted blocks and
    # plain zero initialization. This also rejects read-modify-write and
    # conditional scratch consumption. Keep every original byte on rejection.
    scratch = {name for candidate in candidates for name in candidate[5:]}
    for statement in _walk(top):
        if any(start <= statement.start and statement.end <= end for start, end, *_ in candidates):
            continue
        refs = _names(statement.lhs) | _names(statement.rhs) | _names(statement.condition)
        if refs & scratch and not (statement.kind == 'assign' and statement.lhs[0] == 'id'
                and statement.lhs[1] in scratch and statement.rhs == ('number', '0')):
            return rtl
    result = rtl
    for start, end, dst, src, shift, rem, half_name in reversed(sorted(candidates)):
        replacement = (f"{half_name} = 64'sd1 <<< ({shift} - 1);\n"
                       f"      {dst} = semantic_rne64({src}, {shift}, {half_name} - 65'sd1);")
        result = result[:offset+start] + replacement + result[offset+end:]
    if not known:
        result = result.replace(marker, RNE64_HELPER + marker, 1)
    return result

"""Share operators in generated, signed fixed-point kernels.

This is not a general Verilog rewrite: callers must supply a kernel whose
arithmetic intermediates have the configured signed width, and every operand
and constant fits that signed width. Wide multiply /
divide helper bodies are left intact. Every generated candidate still needs
full-domain simulation and frontend validation before promotion.
"""
from __future__ import annotations
import re
from collections import Counter

OPS = {'+': ('add', 8), '-': ('sub', 8), '*': ('mul', 9), '/': ('div', 9),
       '<<': ('shl', 7), '<<<': ('asl', 7), '>>': ('shr', 7), '>>>': ('asr', 7),
       '>': ('gt', 6), '>=': ('ge', 6), '<': ('lt', 6), '<=': ('le', 6),
       '==': ('eq', 5), '!=': ('ne', 5), '&&': ('land', 2), '||': ('lor', 1)}
COMPARISONS = {'gt', 'ge', 'lt', 'le', 'eq', 'ne', 'land', 'lor'}
TOKEN = re.compile(r"(?:\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|\d+|[A-Za-z_$][\w$]*|>>>|<<<|>>|<<|>=|<=|==|!=|&&|\|\||[(){}\[\],:+*/?<>!-])")


class Expression:
    def __init__(self, text: str, shared_names: set[str] | None = None):
        self.tokens = TOKEN.findall(text)
        if ''.join(self.tokens) != re.sub(r'\s+', '', text):
            raise ValueError('unsupported expression syntax')
        self.pos = 0
        self.used: set[str] = set()
        self.counts: Counter[str] = Counter()
        self.shared_names = shared_names

    def peek(self) -> str:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ''

    def take(self, expected: str | None = None) -> str:
        value = self.peek()
        if not value or (expected is not None and value != expected):
            raise ValueError('unbalanced expression')
        self.pos += 1
        return value

    def primary(self) -> str:
        token = self.take()
        if token in {'-', '+', '!'}:
            return '(' + token + self.primary() + ')'
        if token == '(':
            result = self.parse()
            self.take(')')
            return '(' + result + ')'
        if token == '{':
            # Preserve concatenation widths and signed casts exactly.
            start = self.pos - 1
            depth = 1
            while depth:
                value = self.take()
                depth += (value == '{') - (value == '}')
            return ''.join(self.tokens[start:self.pos])
        result = token
        if self.peek() == '(':
            self.take('(')
            args = []
            while self.peek() != ')':
                args.append(self.parse())
                if self.peek() != ',':
                    break
                self.take(',')
            self.take(')')
            result += '(' + ', '.join(args) + ')'
        while self.peek() == '[':
            start = self.pos
            self.take('[')
            while self.peek() != ']':
                self.take()
            self.take(']')
            result += ''.join(self.tokens[start:self.pos])
        return result

    def parse(self, minimum: int = 0) -> str:
        left = self.primary()
        while self.peek() in OPS and OPS[self.peek()][1] >= minimum:
            operator = self.take()
            name, precedence = OPS[operator]
            right = self.parse(precedence + 1)
            self.counts[name] += 1
            if self.shared_names is None or name in self.shared_names:
                self.used.add(name)
                left = f'fp_{name}({left}, {right})'
            else:
                left = f'({left} {operator} {right})'
        if minimum == 0 and self.peek() == '?':
            self.take('?')
            yes = self.parse()
            self.take(':')
            no = self.parse()
            self.counts['mux'] += 1
            if self.shared_names is None or 'mux' in self.shared_names:
                self.used.add('mux')
                left = f'fp_mux({left}, {yes}, {no})'
            else:
                left = f'({left} ? {yes} : {no})'
        return left


def compact_fixed_point_operators(rtl: str, width: int = 64,
                                  body_start: str | None = None,
                                  min_word_operator_uses: int = 1) -> str:
    """Factor repeated signed-width operators in an emitter's always block.

    An unsupported expression is preserved unchanged. This function does not
    choose representations or costs, infer circuit families, or read filenames.
    """
    if width < 2:
        raise ValueError('fixed-point width must be at least two')
    if min_word_operator_uses < 1:
        raise ValueError('minimum word operator uses must be positive')
    marker = '  always @(*) begin'
    if marker not in rtl:
        return rtl
    header, body = rtl.split(marker, 1)
    # A mixed-width emitter can retain its wide range-reduction prefix and
    # share only its signed fixed-point tail. The boundary is source structure,
    # never a circuit filename or a truth-table row. Missing boundaries fail
    # closed to the original implementation.
    prefix = ''
    if body_start is not None:
        if body.count(body_start) != 1:
            return rtl
        position = body.index(body_start)
        prefix, body = body[:position], body[position:]
    used: set[str] = set()
    counts: Counter[str] = Counter()
    shared_names: set[str] | None = None

    def rewrite(text: str) -> str:
        try:
            expression = Expression(text, shared_names)
            result = expression.parse()
            if expression.pos != len(expression.tokens):
                return text
        except ValueError:
            return text
        used.update(expression.used)
        counts.update(expression.counts)
        return result

    # Only whole procedural assignments, never declarations or helper bodies.
    def rewrite_body(body: str) -> str:
        body = re.sub(r'(?m)^([ \t]*\w+[ \t]*=[ \t]*)([^;]+);',
                  lambda match: match[1] + rewrite(match[2]) + ';', body)
    # Balanced if expressions can include nested function calls / parentheses.
        position = 0
        chunks = []
        while True:
            match = re.search(r'\bif\s*\(', body[position:])
            if match is None:
                chunks.append(body[position:])
                break
            start = position + match.end()
            depth, end = 1, start
            while depth and end < len(body):
                depth += (body[end] == '(') - (body[end] == ')')
                end += 1
            if depth:
                chunks.append(body[position:])
                break
            chunks.append(body[position:start] + rewrite(body[start:end-1]) + ')')
            position = end
        return ''.join(chunks)

    original_body = body
    body = rewrite_body(original_body)
    if min_word_operator_uses > 1:
        # Count on the original signed-width kernel, then render that same
        # kernel again. Single-use operations stay visible in their caller;
        # they are not moved into macros, casts, or uncharged declarations.
        # Scalar predicate helpers retain the established typed contract.
        shared_names = COMPARISONS | {
            name for name, count in counts.items()
            if count >= min_word_operator_uses
        }
        used.clear()
        counts.clear()
        body = rewrite_body(original_body)
    helpers = []
    for name in sorted(used):
        if name == 'mux':
            helpers.append(f'''  function signed [{width-1}:0] fp_mux;
    input signed [{width-1}:0] condition;
    input signed [{width-1}:0] a, b;
    begin fp_mux = condition ? a : b; end
  endfunction
''')
        else:
            operator = next(op for op, (key, _) in OPS.items() if key == name)
            result_type = '' if name in COMPARISONS else f'signed [{width-1}:0] '
            helpers.append(f'''  function {result_type}fp_{name};
    input signed [{width-1}:0] a, b;
    begin fp_{name} = a {operator} b; end
  endfunction
''')
    return header + ''.join(helpers) + marker + prefix + body

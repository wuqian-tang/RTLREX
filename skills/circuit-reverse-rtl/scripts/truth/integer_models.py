"""Learn reusable modular word arithmetic from a complete oracle.

Coefficients come from low-order probes; every accepted model is checked on the
entire domain. There is no filename, corpus identity, lookup or answer dispatch.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence


def signed(value: int, width: int) -> int:
    return value - (1 << width) if value & (1 << (width - 1)) else value


def probes(size: int) -> list[int]:
    values = {0, 1, 2, size - 1, size // 2, max(0, size // 2 - 1)}
    values.update(1 << bit for bit in range(size.bit_length() - 1))
    state = 0x9E3779B9
    for _ in range(32):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        values.add(state & (size - 1))
    return sorted(x for x in values if x < size)


def match(words: Sequence[int], model: Callable[[int], int], selected: list[int]) -> bool:
    if any(model(x) != words[x] for x in selected):
        return False
    return all(model(x) == word for x, word in enumerate(words))


def rtl(n: int, m: int, declarations: list[str], expression: str) -> str:
    return "\n".join([f"module top(input [{n-1}:0] x, output [{m-1}:0] y);",
                      *declarations, f"  assign y = {expression};", "endmodule", ""])


def word(name: str, lo: int, width: int, m: int, is_signed: bool) -> str:
    part = f"x[{lo+width-1}:{lo}]"
    value = f"$signed({part})" if is_signed else part
    return f"  wire [{m-1}:0] {name} = {value};"


def linear_expression(terms: list[tuple[int, str]], constant: int, m: int) -> str:
    mask = (1 << m) - 1
    expression = ""
    for coefficient, name in terms:
        coefficient &= mask
        if not coefficient:
            continue
        negative = coefficient == mask
        term = name if coefficient in (1, mask) else f"{m}'h{coefficient:x} * {name}"
        if not expression:
            expression = ("-" if negative else "") + term
        else:
            expression += (" - " if negative else " + ") + term
    if constant & mask:
        expression += (" + " if expression else "") + f"{m}'h{constant & mask:x}"
    return expression or f"{m}'d0"


def solve_power_two_congruence(multiplier: int, rhs: int, width: int) -> int | None:
    """Return one exact solution of multiplier*q = rhs modulo 2**width.

    Division is permitted only after removing the common power of two.
    The remaining odd factor is invertible; no floating-point fitting or
    division by an even residue is used.
    """
    modulus = 1 << width
    multiplier, rhs = multiplier % modulus, rhs % modulus
    if multiplier == 0:
        return 0 if rhs == 0 else None
    common = multiplier & -multiplier
    if rhs % common:
        return None
    reduced_modulus = modulus // common
    return ((rhs // common) * pow(multiplier // common, -1, reduced_modulus)) % reduced_modulus


def quadratic_axis(first: int, second: int | None, width: int,
                   output_width: int, is_signed: bool) -> tuple[int, int] | None:
    """Fit linear and square coefficients on one finite word field."""
    mask = (1 << output_width) - 1
    unit = signed(1, width) if is_signed else 1
    if width == 1:
        # A one-bit field has only zero and unit (-1 when signed). Its square
        # term is indistinguishable from a linear term on the entire field.
        return first * unit & mask, 0
    value_two = signed(2, width) if is_signed else 2
    quadratic = solve_power_two_congruence(
        value_two * value_two - value_two * unit,
        int(second) - value_two * unit * first, output_width)
    if quadratic is None:
        return None
    linear = (first - quadratic) * unit & mask
    # For width>=2, unit=1 and the divisor is 2 (unsigned) or 6 (signed 2-bit).
    # The alternative root differs by 2**(m-1), with opposite linear change;
    # its effect is 2**(m-1)*a*(a-1), identically zero modulo 2**m.
    return linear, quadratic


def infer_packed_quadratic(n: int, m: int, words: Sequence[int],
                           selected: list[int] | None = None) -> tuple[str, str] | None:
    """Learn c0+c1*a+c2*b+c3*a*a+c4*a*b+c5*b*b for all word splits.

    Six axis/cross probes identify a candidate over Z/(2**m). Additional
    probes reject wrong candidates cheaply, but acceptance always checks
    every raw input word. Field values and overflow are parameters, never
    corpus identities or interface-shape dispatch keys.
    """
    if not (2 <= n <= 18 and m >= 1 and len(words) == 1 << n):
        return None
    mask = (1 << m) - 1
    selected = probes(len(words)) if selected is None else selected
    constant = words[0]
    for split in range(1, n):
        high_width, low_mask = n - split, (1 << split) - 1
        low_first = (words[1] - constant) & mask
        high_first = (words[1 << split] - constant) & mask
        low_second = (words[2] - constant) & mask if split >= 2 else None
        high_second = (words[2 << split] - constant) & mask if high_width >= 2 else None
        cross = (words[1 | (1 << split)] - words[1] - words[1 << split] + constant) & mask
        for low_signed, high_signed in ((False, False), (True, True), (True, False), (False, True)):
            low = quadratic_axis(low_first, low_second, split, m, low_signed)
            high = quadratic_axis(high_first, high_second, high_width, m, high_signed)
            if low is None or high is None:
                continue
            c1, c3 = low
            c2, c5 = high
            low_unit = signed(1, split) if low_signed else 1
            high_unit = signed(1, high_width) if high_signed else 1
            c4 = cross * low_unit * high_unit & mask
            def model(x: int) -> int:
                a, b = x & low_mask, x >> split
                if low_signed:
                    a = signed(a, split)
                if high_signed:
                    b = signed(b, high_width)
                return (constant + c1*a + c2*b + c3*a*a + c4*a*b + c5*b*b) & mask
            if not match(words, model, selected):
                continue
            expression = linear_expression(
                [(c1, 'a'), (c2, 'b'), (c3, 'a * a'), (c4, 'a * b'), (c5, 'b * b')], constant, m)
            return ('packed modular quadratic words',
                    rtl(n, m, [word('a', 0, split, m, low_signed),
                               word('b', split, high_width, m, high_signed)], expression))
    return None


def infer_integer_model(n: int, m: int, words: Sequence[int]) -> tuple[str, str] | None:
    if not (1 <= n <= 18 and m >= 1 and len(words) == 1 << n):
        return None
    mask = (1 << m) - 1
    selected = probes(len(words))
    constant = words[0]
    for is_signed in (False, True):
        unit = signed(1, n) if is_signed else 1
        coefficient = ((words[1] - constant) * unit) & mask
        value = (lambda x: signed(x, n)) if is_signed else (lambda x: x)
        model = lambda x: (coefficient * value(x) + constant) & mask
        if match(words, model, selected):
            return ("signed modular affine word" if is_signed else "unsigned modular affine word",
                    rtl(n, m, [word("a", 0, n, m, is_signed)],
                        linear_expression([(coefficient, "a")], constant, m)))
    if n >= 2:
        # Two-adic quadratic inference has two possible leading coefficients;
        # neither is accepted from probes alone.
        difference = (words[2] - 2 * words[1] + constant) & mask
        if not difference & 1:
            for quadratic in {difference // 2, (difference // 2 + (1 << (m-1))) & mask}:
                linear = (words[1] - constant - quadratic) & mask
                model = lambda x: (quadratic*x*x + linear*x + constant) & mask
                if match(words, model, selected):
                    expression = linear_expression([(quadratic, "a * a"), (linear, "a")], constant, m)
                    return "unsigned modular quadratic word", rtl(n, m, [word("a", 0, n, m, False)], expression)
    for split in range(1, n):
        high_width = n - split
        low_mask = (1 << split) - 1
        for low_signed, high_signed in ((False, False), (True, True), (True, False), (False, True)):
            low_unit = signed(1, split) if low_signed else 1
            high_unit = signed(1, high_width) if high_signed else 1
            a = ((words[1] - constant) * low_unit) & mask
            b = ((words[1 << split] - constant) * high_unit) & mask
            def parts(x: int) -> tuple[int, int]:
                low, high = x & low_mask, x >> split
                return (signed(low, split) if low_signed else low,
                        signed(high, high_width) if high_signed else high)
            def model(x: int) -> int:
                low, high = parts(x)
                return (a*low + b*high + constant) & mask
            if match(words, model, selected):
                return ("packed modular affine words",
                        rtl(n, m, [word("a", 0, split, m, low_signed),
                                   word("b", split, high_width, m, high_signed)],
                            linear_expression([(a, "a"), (b, "b")], constant, m)))
        # Comparisons and min/max retain native comparison widths, even when
        # the result is narrower. Both signed operands are extended by Verilog.
        for is_signed in (False, True):
            def parts(x: int) -> tuple[int, int]:
                low, high = x & low_mask, x >> split
                return (signed(low, split) if is_signed else low,
                        signed(high, high_width) if is_signed else high)
            sign = "signed " if is_signed else ""
            declarations = [f"  wire {sign}[{split-1}:0] a = x[{split-1}:0];",
                            f"  wire {sign}[{high_width-1}:0] b = x[{n-1}:{split}];"]
            operations = (
                ("equal", lambda a, b: int(a == b), "a == b"),
                ("unequal", lambda a, b: int(a != b), "a != b"),
                ("less", lambda a, b: int(a < b), "a < b"),
                ("less_equal", lambda a, b: int(a <= b), "a <= b"),
                ("greater", lambda a, b: int(a > b), "a > b"),
                ("greater_equal", lambda a, b: int(a >= b), "a >= b"),
                ("minimum", min, "(a < b) ? a : b"),
                ("maximum", max, "(a > b) ? a : b"),
            )
            for label, operation, expression in operations:
                model = lambda x: operation(*parts(x)) & mask
                if match(words, model, selected):
                    return f"{sign or 'unsigned '}{label} of packed words", rtl(n, m, declarations, expression)
        # Unsigned saturation is separate from modular arithmetic.
        declarations = [f"  wire [{n-1}:0] a = x[{split-1}:0];",
                        f"  wire [{n-1}:0] b = x[{n-1}:{split}];",
                        f"  wire [{n}:0] sum = {{1'b0, a}} + {{1'b0, b}};"]
        model = lambda x: min(mask, (x & low_mask) + (x >> split))
        if match(words, model, selected):
            return "unsigned saturating sum", rtl(n, m, declarations,
                f"(sum > {max(n+1,m)}'h{mask:x}) ? {m}'h{mask:x} : sum")
    return infer_packed_quadratic(n, m, words, selected)

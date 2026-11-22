"""Infer at most four wide endpoint regions of a unary floating-point map.

Only normal finite magnitudes are examined. A region must span at least a
complete mantissa field; isolated corrections and interior partitions are
never emitted. The remaining kernel still requires complete-domain proof.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class EndpointRegion:
    sign: int
    lower: int
    upper: int
    operation: str
    value: int | None

    @property
    def count(self) -> int:
        return self.upper - self.lower + 1


def infer_endpoint_regions(words: Sequence[int], exponent_bits: int,
                           mantissa_bits: int) -> list[EndpointRegion]:
    width = 1 + exponent_bits + mantissa_bits
    if len(words) != 1 << width or any(v < 0 or v >= 1 << width for v in words):
        raise ValueError("Complete same-width unsigned floating-point map required")
    normal_first = 1 << mantissa_bits
    normal_last = (((1 << exponent_bits) - 1) << mantissa_bits) - 1
    sign_bit = 1 << (width - 1)
    minimum_count = 1 << mantissa_bits
    regions = []
    for sign in (0, 1):
        base = sign * sign_bit
        prefix_options = []
        for operation in ("identity", "constant"):
            value = words[base + normal_first]
            stop = normal_first
            while stop <= normal_last and words[base + stop] == (
                    base + stop if operation == "identity" else value):
                stop += 1
            if stop - normal_first >= minimum_count:
                prefix_options.append(EndpointRegion(sign, normal_first, stop - 1,
                    operation, None if operation == "identity" else value))
        prefix = max(prefix_options, key=lambda r: (r.count, r.operation == "identity"),
                     default=None)
        if prefix is not None:
            regions.append(prefix)
        floor = prefix.upper + 1 if prefix else normal_first
        value = words[base + normal_last]
        stop = normal_last
        while stop >= floor and words[base + stop] == value:
            stop -= 1
        if normal_last - stop >= minimum_count:
            regions.append(EndpointRegion(sign, stop + 1, normal_last, "constant", value))
    return regions


def emit_endpoint_guards(words: Sequence[int] | None, exponent_bits: int = 5,
                         mantissa_bits: int = 10) -> str:
    if words is None:
        return ""
    width = 1 + exponent_bits + mantissa_bits
    regions = infer_endpoint_regions(words, exponent_bits, mantissa_bits)
    clauses = []
    for region in regions:
        condition = (f"x[{width - 1}] == 1'b{region.sign} && "
                     f"x[{width - 2}:0] >= {width - 1}'h{region.lower:x} && "
                     f"x[{width - 2}:0] <= {width - 1}'h{region.upper:x}")
        result = "x" if region.operation == "identity" else f"{width}'h{region.value:04x}"
        clauses.append(f" end else if ({condition}) begin\n"
                       f"      // Exact continuous {region.operation} region: {region.count} inputs.\n"
                       f"      y = {result};\n")
    return "".join(clauses)


def isolate_endpoint_kernel(template: str, words: Sequence[int] | None,
                            exponent_bits: int = 5, mantissa_bits: int = 10) -> str:
    """Clamp kernel operands where a proven endpoint or exception returns.

    A continuous input mux survives process lowering. Merely guarding the
    output does not prevent the lowered combinational arithmetic from changing
    on every bypassed input. Output and exceptional-value decisions still use x.
    """
    if words is None:
        return template
    width = 1 + exponent_bits + mantissa_bits
    conditions = []
    for r in infer_endpoint_regions(words, exponent_bits, mantissa_bits):
        conditions.append(f"(x[{width - 1}] == 1'b{r.sign} && "
            f"x[{width - 2}:0] >= {width - 1}'h{r.lower:x} && "
            f"x[{width - 2}:0] <= {width - 1}'h{r.upper:x})")
    exponent = f"x[{width - 2}:{mantissa_bits}]"
    conditions.extend((f"({exponent} == {exponent_bits}'d0)",
                       f"({exponent} == {exponent_bits}'d{(1 << exponent_bits) - 1})"))
    # Floating-point +1 is a finite normal safe operand, independent of the map.
    one = ((1 << (exponent_bits - 1)) - 1) << mantissa_bits
    declaration = (f"  wire [{width - 1}:0] kernel_x =\n    (" +
                   " ||\n     ".join(conditions) +
                   f") ? {width}'h{one:x} : x;\n\n")
    assert template.count("  always @(*) begin") == 1
    template = template.replace("  always @(*) begin", declaration + "  always @(*) begin", 1)
    expression = "aq = (64'sd1024 + frac) <<< (xe + 15);"
    replacement = "aq = (64'sd1024 + kernel_x[9:0]) <<< (kernel_x[14:10] + 15);"
    assert exponent_bits == 5 and mantissa_bits == 10, "Kernel hook is FP16 Q40 only"
    assert template.count(expression) == 1
    template = template.replace(expression, replacement, 1)
    # Keep the original sign for the exceptional/output decisions, while the
    # logistic kernel's sign-sensitive exponential uses the isolated word.
    if "limitq = xs ? NLIMIT : PLIMIT;" in template:
        template = template.replace("limitq = xs ? NLIMIT : PLIMIT;",
                                    "limitq = kernel_x[15] ? NLIMIT : PLIMIT;", 1)
        assert template.count("if (xs)\n          eq =") == 1
        template = template.replace("if (xs)\n          eq =",
                                    "if (kernel_x[15])\n          eq =", 1)
    return template


def region_records(words: Sequence[int], exponent_bits: int = 5,
                   mantissa_bits: int = 10) -> list[dict]:
    return [dict(asdict(r), count=r.count) for r in
            infer_endpoint_regions(words, exponent_bits, mantissa_bits)]

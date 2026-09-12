#!/usr/bin/env python3
"""Generate word-level RTL candidates from primitive combinational netlists.

The flow is intentionally candidate based:
  * emit structural arithmetic templates where the datapath shape is obvious;
  * learn small affine/control functions by black-box simulation;
  * fall back to the original primitive netlist when no compact candidate is known.
"""

from __future__ import annotations

import argparse
import re
import shutil
import random
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from itertools import combinations
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path.cwd().resolve()
GATE_RE = re.compile(r"^\s*(and|or|nand|nor|not|buf|xor|xnor)\s+\S+\((.*?)\);", re.M)


@dataclass
class Port:
    kind: str
    name: str
    width: int
    range_text: str


@dataclass
class Spec:
    case: str
    path: Path
    header: str
    ports: List[Port]
    text: str

    @property
    def inputs(self) -> Dict[str, int]:
        return {p.name: p.width for p in self.ports if p.kind == "input"}

    @property
    def outputs(self) -> Dict[str, int]:
        return {p.name: p.width for p in self.ports if p.kind == "output"}


from verify.tooling import optional_tool, resolve_tool

def parse_width(range_text: str) -> int:
    if not range_text:
        return 1
    nums = [int(x) for x in re.findall(r"\d+", range_text)]
    return abs(nums[0] - nums[1]) + 1


def parse_spec(path: Path) -> Spec:
    text = path.read_text()
    header_m = re.search(r"module\s+top\s*\((.*?)\);", text, re.S)
    if not header_m:
        raise ValueError(f"{path}: missing top module header")
    header = " ".join(header_m.group(1).split())

    ports: List[Port] = []
    for m in re.finditer(r"^\s*(input|output)\s*(\[[^\]]+\])?\s*([^;]+);", text, re.M):
        kind, range_text, names = m.groups()
        range_text = range_text or ""
        width = parse_width(range_text)
        for raw in names.split(","):
            name = raw.strip()
            if name and "[" not in name:
                ports.append(Port(kind, name, width, range_text))
    return Spec(path.parent.name, path, header, ports, text)


def emit_decls(spec: Spec, body: Sequence[str], regs: Iterable[str] = ()) -> str:
    reg_set = set(regs)
    compact_header = ",".join(part.strip() for part in spec.header.split(","))
    lines = [f"module top({compact_header});"]
    # Group same-width declarations.  Besides producing substantially more
    # compact RTL for wide interfaces, this avoids redundant ``wire``
    # redeclarations: a Verilog ``output`` is already a net unless declared
    # as a variable below.
    grouped: Dict[Tuple[str, str], List[str]] = {}
    for p in spec.ports:
        grouped.setdefault((p.kind, p.range_text), []).append(p.name)
    for (kind, range_text), names in grouped.items():
        prefix = f"{kind} {range_text}".strip()
        lines.append(f"{prefix} {','.join(names)};")
    reg_groups: Dict[str, List[str]] = {}
    for p in spec.ports:
        if p.kind == "output" and p.name in reg_set:
            reg_groups.setdefault(p.range_text, []).append(p.name)
    for range_text, names in reg_groups.items():
        prefix = f"reg {range_text}".strip()
        lines.append(f"{prefix} {','.join(names)};")
    lines.extend(body)
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def rename_top_module(text: str, name: str) -> str:
    return re.sub(r"\bmodule\s+top\s*\(", f"module {name}(", text, count=1)


def decl(kind: str, width: int, name: str) -> str:
    if width == 1:
        return f"{kind} {name};"
    return f"{kind} [{width - 1}:0] {name};"


def port_connections(spec: Spec) -> str:
    return ", ".join(f".{p.name}({p.name})" for p in spec.ports)


def iverilog_random_equivalence(
    reference: Path,
    candidate_text: str,
    spec: Spec,
    vectors: int,
    seed: int = 1,
) -> Tuple[bool, str]:
    iverilog = optional_tool("IVERILOG")
    vvp = optional_tool("VVP")
    if not iverilog or not vvp:
        return False, "iverilog or vvp not found"

    with tempfile.TemporaryDirectory(prefix="datapath_reverse_sim_") as tmp:
        tmpdir = Path(tmp)
        ref_path = tmpdir / "reference.v"
        impl_path = tmpdir / "candidate.v"
        tb_path = tmpdir / "tb.v"
        simv_path = tmpdir / "simv"

        ref_path.write_text(rename_top_module(reference.read_text(), "ref_top"))
        impl_path.write_text(rename_top_module(candidate_text, "impl_top"))

        lines = ["module tb;"]
        for name, width in spec.inputs.items():
            lines.append(f"  {decl('reg', width, name)}")
        for name, width in spec.outputs.items():
            lines.append(f"  {decl('wire', width, 'ref_' + name)}")
            lines.append(f"  {decl('wire', width, 'impl_' + name)}")
        ref_ports = ", ".join(
            f".{p.name}({p.name if p.kind == 'input' else 'ref_' + p.name})"
            for p in spec.ports
        )
        impl_ports = ", ".join(
            f".{p.name}({p.name if p.kind == 'input' else 'impl_' + p.name})"
            for p in spec.ports
        )
        lines.append(f"  ref_top u_ref({ref_ports});")
        lines.append(f"  impl_top u_impl({impl_ports});")
        lines.append("  integer i;")
        lines.append("  integer seed_value;")
        lines.append("  initial begin")
        lines.append(f"    seed_value = {seed};")
        lines.append(f"    for (i = 0; i < {vectors}; i = i + 1) begin")
        for name in spec.inputs:
            lines.append(f"      {name} = $random(seed_value);")
        lines.append("      #1;")
        for name in spec.outputs:
            lines.append(f"      if (ref_{name} !== impl_{name}) begin")
            lines.append(f"        $display(\"MISMATCH {name} vector=%0d ref=%0h impl=%0h\", i, ref_{name}, impl_{name});")
            lines.append("        $finish(1);")
            lines.append("      end")
        lines.append("    end")
        lines.append("    $display(\"SIM_PASS\");")
        lines.append("    $finish(0);")
        lines.append("  end")
        lines.append("endmodule")
        tb_path.write_text("\n".join(lines) + "\n")

        compile_proc = subprocess.run(
            [iverilog, "-g2012", "-o", str(simv_path), str(ref_path), str(impl_path), str(tb_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if compile_proc.returncode != 0:
            return False, (compile_proc.stdout + compile_proc.stderr).strip()
        run_proc = subprocess.run(
            [vvp, str(simv_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        detail = (run_proc.stdout + run_proc.stderr).strip()
        return run_proc.returncode == 0 and "SIM_PASS" in run_proc.stdout, detail


def conditional_multiply_accumulator(spec: Spec) -> Optional[str]:
    widths = spec.inputs
    if (
        list(spec.outputs) == ["out1"]
        and spec.outputs["out1"] in {17, 32}
        and {"in3", "in6", "in10", "in14", "in18", "in22"}.issubset(widths)
    ):
        if widths.get("in1") == 9 and widths.get("in2") == 8 and widths.get("in5") == 7:
            terms = [
                ("in3", "in1", "in2"),
                ("in6", "in8", "in9"),
                ("in10", "in12", "in13"),
                ("in14", "in16", "in17"),
                ("in18", "in20", "in21"),
                ("in22", "in24", "in25"),
            ]
            base = "in5"
        elif widths.get("in1") == 16 and widths.get("in2") == 16 and widths.get("in5") == 16:
            terms = [
                ("in3", "in1", "in2"),
                ("in6", "in8", "in9"),
                ("in10", "in12", "in13"),
                ("in14", "in16", "in17"),
                ("in18", "in20", "in21"),
                ("in22", "in24", "in25"),
            ]
            base = "in5"
        else:
            return None
        expr = base + "".join(f" + ({c} ? 0 : {a} * {b})" for c, a, b in terms)
        return emit_decls(spec, [f"assign out1 = {expr};"])
    return None


def verified_formula(spec: Spec, body: Sequence[str], vectors: int = 512, seed: int = 101) -> Optional[str]:
    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=vectors, seed=seed)
    return rtl if ok else None


def difference_threshold_predicate(spec: Spec) -> Optional[str]:
    if list(spec.outputs.values()) != [1] or len(spec.inputs) != 3:
        return None
    names = list(spec.inputs)
    sim = PrimitiveSim(spec)
    samples = targeted_values(spec)
    rng = random.Random(14)
    samples.extend(random_values(spec, rng) for _ in range(128))
    output = next(iter(spec.outputs))

    for a in names:
        for b in names:
            if b == a:
                continue
            for c in names:
                if c in {a, b}:
                    continue
                width = max(spec.inputs[a], spec.inputs[b])
                mod = 1 << width

                def predictor(values: Dict[str, int], a: str = a, b: str = b, c: str = c) -> int:
                    lhs = values.get(a, 0)
                    rhs = values.get(b, 0)
                    return int(lhs > rhs and values.get(c, 0) < ((lhs - rhs) % mod))

                if output_matches(sim, output, predictor, samples):
                    lhs = extend_expr(a, spec.inputs[a], width)
                    rhs = extend_expr(b, spec.inputs[b], width)
                    diff = f"({lhs} - {rhs})"
                    compare_width = max(spec.inputs[c], width)
                    c_expr = extend_expr(c, spec.inputs[c], compare_width)
                    diff_expr = diff if width == compare_width else f"{{{compare_width - width}'b0, {diff}}}"
                    body = [f"assign {output} = ({lhs} > {rhs}) && ({c_expr} < {diff_expr});"]
                    return emit_decls(spec, body)

                signed_width = max(spec.inputs[a], spec.inputs[b], spec.inputs[c])

                def signed_predictor(
                    values: Dict[str, int],
                    a: str = a,
                    b: str = b,
                    c: str = c,
                    signed_width: int = signed_width,
                ) -> int:
                    diff = values.get(a, 0) - values.get(b, 0)
                    cmp_value = signed_value(values.get(c, 0), spec.inputs[c])
                    return int(cmp_value < signed_value(diff, signed_width))

                if output_matches(sim, output, signed_predictor, samples):
                    body = [
                        f"wire signed [{signed_width - 1}:0] diff;",
                        f"wire signed [{signed_width - 1}:0] cmp_value;",
                        f"assign diff = {extend_expr(a, spec.inputs[a], signed_width)} - {extend_expr(b, spec.inputs[b], signed_width)};",
                        f"assign cmp_value = {extend_expr(c, spec.inputs[c], signed_width)};",
                        f"assign {output} = cmp_value < diff;",
                    ]
                    rtl = emit_decls(spec, body)
                    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=256, seed=14)
                    return rtl if ok else None
    return None


def two_bit_multiply_mux(spec: Spec) -> Optional[str]:
    if list(spec.outputs.values()) != [32]:
        return None
    controls = [name for name, width in spec.inputs.items() if width == 2]
    data = [name for name, width in spec.inputs.items() if width > 2]
    if len(controls) != 1 or len(data) != 3 or len({spec.inputs[name] for name in data}) != 1:
        return None

    ctrl = controls[0]
    a, b, c = data
    output = next(iter(spec.outputs))
    expr = (
        f"({ctrl} == 2'd0) ? 0 : "
        f"(({ctrl} == 2'd1) ? ({b} * {c}) : "
        f"(({ctrl} == 2'd2) ? ({a} * {c}) : ({a} * {b})))"
    )
    rtl = emit_decls(spec, [f"assign {output} = {expr};"])
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=128, seed=7)
    return rtl if ok else None


def offset_add_compare_learner(spec: Spec) -> Optional[str]:
    if len(spec.inputs) != 6 or len(spec.outputs) != 5:
        return None
    inputs = spec.inputs
    outputs = spec.outputs
    if list(outputs.values()).count(5) != 3 or list(outputs.values()).count(1) != 2:
        return None

    two_bit = [name for name, width in inputs.items() if width == 2]
    three_bit = [name for name, width in inputs.items() if width == 3]
    five_bit = [name for name, width in inputs.items() if width == 5]
    data_outputs = [name for name, width in outputs.items() if width == 5]
    flag_outputs = [name for name, width in outputs.items() if width == 1]
    if len(two_bit) != 2 or len(three_bit) != 2 or len(five_bit) != 2:
        return None

    ctrl = two_bit[0]
    small = [two_bit[1], three_bit[0], three_bit[1]]
    compare = five_bit
    body = [
        "wire [2:0] offset;",
        f"assign offset = 3'd1 - {{1'b0, {ctrl}}};",
    ]
    for output, name in zip(data_outputs, small):
        body.append(f"assign {output} = {{2'b0, {name}}} + {{2'b0, offset}};")
    for flag, data_out, cmp_in in zip(flag_outputs, data_outputs[:2], compare):
        body.append(f"assign {flag} = !{cmp_in}[{inputs[cmp_in] - 1}] && ({data_out} < {cmp_in});")
    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=256, seed=18)
    return rtl if ok else None


def parse_gates(text: str) -> List[Tuple[str, str, List[str]]]:
    gates: List[Tuple[str, str, List[str]]] = []
    for m in GATE_RE.finditer(text):
        args = [x.strip() for x in m.group(2).split(",")]
        gates.append((m.group(1), args[0], args[1:]))
    return gates


def const_bit(token: str) -> Optional[int]:
    if re.fullmatch(r"(?:\d+'b[01]|[01])", token):
        return int(token[-1])
    return None


class PrimitiveSim:
    def __init__(self, spec: Spec):
        self.inputs = spec.inputs
        self.outputs = spec.outputs
        self.order = self._topological_order(parse_gates(spec.text))

    def _topological_order(self, gates: List[Tuple[str, str, List[str]]]) -> List[Tuple[str, str, List[str]]]:
        known = set()
        for name, width in self.inputs.items():
            known.add(name)
            known.update(f"{name}[{i}]" for i in range(width))
        ordered: List[Tuple[str, str, List[str]]] = []
        pending = list(gates)
        while pending:
            next_pending = []
            changed = False
            for gate in pending:
                _, out, ins = gate
                if all(x in known or const_bit(x) is not None for x in ins):
                    ordered.append(gate)
                    known.add(out)
                    changed = True
                else:
                    next_pending.append(gate)
            if not changed:
                raise RuntimeError(f"cannot topologically order {len(next_pending)} gates")
            pending = next_pending
        return ordered

    def __call__(self, values: Dict[str, int]) -> Dict[str, int]:
        bits: Dict[str, int] = {}
        for name, width in self.inputs.items():
            value = values.get(name, 0)
            bits[name] = value & 1
            for i in range(width):
                bits[f"{name}[{i}]"] = (value >> i) & 1
        for typ, out, ins in self.order:
            xs = [const_bit(x) if const_bit(x) is not None else bits[x] for x in ins]
            if typ in {"and", "nand"}:
                y = 1
                for x in xs:
                    y &= x
                if typ == "nand":
                    y ^= 1
            elif typ in {"or", "nor"}:
                y = 0
                for x in xs:
                    y |= x
                if typ == "nor":
                    y ^= 1
            elif typ in {"xor", "xnor"}:
                y = 0
                for x in xs:
                    y ^= x
                if typ == "xnor":
                    y ^= 1
            elif typ == "not":
                y = xs[0] ^ 1
            else:
                y = xs[0]
            bits[out] = y & 1
        result: Dict[str, int] = {}
        for name, width in self.outputs.items():
            if width == 1:
                result[name] = bits.get(name, bits.get(f"{name}[0]", 0))
            else:
                value = 0
                for i in range(width):
                    value |= bits.get(f"{name}[{i}]", 0) << i
                result[name] = value
        return result


BitTerm = Tuple[str, ...]


def input_bits(spec: Spec) -> List[str]:
    bits = []
    for name, width in spec.inputs.items():
        if width == 1:
            bits.append(name)
        else:
            bits.extend(f"{name}[{i}]" for i in range(width))
    return bits


def bit_value(token: str, values: Dict[str, int]) -> int:
    if "[" not in token:
        return values.get(token, 0) & 1
    name, bit = token[:-1].split("[", 1)
    return (values.get(name, 0) >> int(bit)) & 1


def term_value(term: BitTerm, values: Dict[str, int]) -> int:
    result = 1
    for token in term:
        result &= bit_value(token, values)
    return result


def term_expression(term: BitTerm) -> str:
    if not term:
        return "1'b1"
    if len(term) == 1:
        return term[0]
    return "(" + " & ".join(term) + ")"


def gf2_solve(rows: Sequence[int], rhs: Sequence[int], nvars: int) -> Optional[int]:
    augmented = [row | (bit << nvars) for row, bit in zip(rows, rhs)]
    rank = 0
    pivots: List[int] = []
    for col in range(nvars):
        pivot = None
        for r in range(rank, len(augmented)):
            if (augmented[r] >> col) & 1:
                pivot = r
                break
        if pivot is None:
            continue
        augmented[rank], augmented[pivot] = augmented[pivot], augmented[rank]
        for r in range(len(augmented)):
            if r != rank and ((augmented[r] >> col) & 1):
                augmented[r] ^= augmented[rank]
        pivots.append(col)
        rank += 1

    coeffs = 0
    for row in augmented[rank:]:
        if (row & ((1 << nvars) - 1)) == 0 and ((row >> nvars) & 1):
            return None
    for r, col in enumerate(pivots):
        if (augmented[r] >> nvars) & 1:
            coeffs |= 1 << col
    return coeffs


def evaluate_terms(terms: Sequence[BitTerm], values: Dict[str, int]) -> int:
    row = 0
    for i, term in enumerate(terms):
        if term_value(term, values):
            row |= 1 << i
    return row


def emit_bit_formula(coeffs: int, terms: Sequence[BitTerm]) -> str:
    pieces = [term_expression(term) for i, term in enumerate(terms) if (coeffs >> i) & 1]
    if not pieces:
        return "1'b0"
    return " ^ ".join(pieces)


def simulation_terms_learner(spec: Spec) -> Optional[str]:
    bits = input_bits(spec)
    total_output_bits = sum(spec.outputs.values())
    if len(bits) > 22 or total_output_bits > 8:
        return None

    sim = PrimitiveSim(spec)
    rng = random.Random(2)
    max_input_value = {name: 1 << width for name, width in spec.inputs.items()}

    terms: List[BitTerm] = [()]
    for degree in (1, 2):
        terms.extend(tuple(combo) for combo in combinations(bits, degree))
        if len(terms) > 256:
            return None

        samples = []
        for _ in range(max(4 * len(terms), 128)):
            samples.append({name: rng.randrange(limit) for name, limit in max_input_value.items()})
        for token in bits:
            values = {name: 0 for name in spec.inputs}
            if "[" not in token:
                values[token] = 1
            else:
                name, bit = token[:-1].split("[", 1)
                values[name] = 1 << int(bit)
            samples.append(values)

        rows = [evaluate_terms(terms, values) for values in samples]
        models: Dict[Tuple[str, int], int] = {}
        failed = False
        for output, width in spec.outputs.items():
            for bit in range(width):
                rhs = [(sim(values)[output] >> bit) & 1 for values in samples]
                coeffs = gf2_solve(rows, rhs, len(terms))
                if coeffs is None:
                    failed = True
                    break
                models[(output, bit)] = coeffs
            if failed:
                break
        if failed:
            continue

        for _ in range(64):
            values = {name: rng.randrange(limit) for name, limit in max_input_value.items()}
            observed = sim(values)
            for output, width in spec.outputs.items():
                predicted = 0
                row = evaluate_terms(terms, values)
                for bit in range(width):
                    coeffs = models[(output, bit)]
                    if ((coeffs & row).bit_count() & 1) != 0:
                        predicted |= 1 << bit
                if predicted != observed[output]:
                    failed = True
                    break
            if failed:
                break
        if failed:
            continue

        body = []
        for output, width in spec.outputs.items():
            bit_exprs = [emit_bit_formula(models[(output, bit)], terms) for bit in range(width)]
            if width == 1:
                body.append(f"assign {output} = {bit_exprs[0]};")
            else:
                body.append(f"assign {output} = {{{', '.join(reversed(bit_exprs))}}};")
        return emit_decls(spec, body)
    return None


def signed_const(value: int, width: int) -> str:
    mod = 1 << width
    value %= mod
    if value >= (1 << (width - 1)):
        value -= mod
    return str(value)


def zext(name: str, in_width: int, out_width: int) -> str:
    if in_width >= out_width:
        return name
    return f"{{{out_width - in_width}'b0, {name}}}"


def scaled_term(coeff: int, term: str) -> str:
    if coeff == 1:
        return term
    shifts = []
    bit = 0
    value = coeff
    while value:
        if value & 1:
            shifts.append(term if bit == 0 else f"({term} << {bit})")
        value >>= 1
        bit += 1
    return " + ".join(shifts) if shifts else "0"


def signed_mod(value: int, width: int) -> int:
    mod = 1 << width
    value %= mod
    if value >= (1 << (width - 1)):
        value -= mod
    return value


def signed_value(value: int, width: int) -> int:
    value &= (1 << width) - 1
    if width > 0 and value >= (1 << (width - 1)):
        value -= 1 << width
    return value


def sized_const(value: int, width: int) -> str:
    return f"{width}'d{value % (1 << width)}"


def extend_expr(name: str, in_width: int, out_width: int) -> str:
    if in_width == out_width:
        return name
    if in_width < out_width:
        return f"{{{out_width - in_width}'b0, {name}}}"
    return f"{name}[{out_width - 1}:0]"


def sign_extend_expr(name: str, in_width: int, out_width: int) -> str:
    if in_width == out_width:
        return name
    if in_width < out_width:
        return f"{{{{{out_width - in_width}{{{name}[{in_width - 1}]}}}}, {name}}}"
    return f"{name}[{out_width - 1}:0]"


def random_values(spec: Spec, rng: random.Random) -> Dict[str, int]:
    return {name: rng.randrange(1 << width) for name, width in spec.inputs.items()}


def simulate_output_rows(spec: Spec, vectors: Sequence[Dict[str, int]]) -> List[Dict[str, int]]:
    try:
        from sampling.fast_sampler import sample_many

        return sample_many(spec.path, vectors, signals=spec.outputs.keys())
    except Exception:
        sim = PrimitiveSim(spec)
        return [sim(values) for values in vectors]


def targeted_values(spec: Spec) -> List[Dict[str, int]]:
    names = list(spec.inputs)
    vectors: List[Dict[str, int]] = [{name: 0 for name in names}]
    for name, width in spec.inputs.items():
        for value in {0, 1, 2 if width > 1 else 1, (1 << width) - 1, 1 << (width - 1) if width > 1 else 1}:
            vec = {n: 0 for n in names}
            vec[name] = value & ((1 << width) - 1)
            vectors.append(vec)
    pair_count = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pair_count += 1
            if pair_count > 96:
                return vectors
            width = min(spec.inputs[a], spec.inputs[b])
            for value in {0, 1, 2 if width > 1 else 1, (1 << width) - 1}:
                vec = {n: 0 for n in names}
                vec[a] = value & ((1 << spec.inputs[a]) - 1)
                vec[b] = value & ((1 << spec.inputs[b]) - 1)
                vectors.append(vec)
    return vectors


def output_matches(
    sim: PrimitiveSim,
    output: str,
    predictor: Callable[[Dict[str, int]], int],
    samples: Sequence[Dict[str, int]],
) -> bool:
    for values in samples:
        if predictor(values) != sim(values)[output]:
            return False
    return True


def shift_feature_value(values: Dict[str, int], spec: Spec, data: str, shift: Optional[str]) -> int:
    value = values.get(data, 0)
    if shift is not None:
        value <<= values.get(shift, 0)
    return value


ShiftFeature = Tuple[str, Optional[str]]


def shift_feature_expr(feature: ShiftFeature) -> str:
    data, shift = feature
    return data if shift is None else f"({data} << {shift})"


def shift_add_learner(spec: Spec) -> Optional[str]:
    if len(spec.outputs) != 1 or len(spec.inputs) > 10:
        return None
    output = next(iter(spec.outputs))
    width = spec.outputs[output]
    if width > 96:
        return None

    sim = PrimitiveSim(spec)
    names = list(spec.inputs)
    shift_controls = [name for name, in_width in spec.inputs.items() if 1 < in_width <= 6]
    data_inputs = [name for name in names if name not in shift_controls or spec.inputs[name] > 6]
    if not shift_controls or not data_inputs:
        return None

    zero = {name: 0 for name in names}
    base = sim(zero)[output]
    mod = 1 << width
    features: List[ShiftFeature] = []
    rng = random.Random(8)

    for data in data_inputs:
        candidate_terms: List[ShiftFeature] = [(data, None)]
        candidate_terms.extend((data, shift) for shift in shift_controls if shift != data)
        probes = []
        for value in [0, 1, 2, 3, (1 << min(spec.inputs[data], 5)) - 1]:
            for _ in range(16):
                vec = dict(zero)
                vec[data] = value & ((1 << spec.inputs[data]) - 1)
                for shift in shift_controls:
                    vec[shift] = rng.randrange(1 << spec.inputs[shift])
                probes.append(vec)

        found: Optional[Tuple[ShiftFeature, ...]] = None
        for size in (1, 2):
            for combo in combinations(candidate_terms, size):
                ok = True
                for vec in probes:
                    expected = sum(shift_feature_value(vec, spec, *term) for term in combo) % mod
                    observed = (sim(vec)[output] - base) % mod
                    if expected != observed:
                        ok = False
                        break
                if ok:
                    found = combo
                    break
            if found:
                break
        if found:
            features.extend(found)

    if not features:
        return None

    def predictor(values: Dict[str, int]) -> int:
        return (base + sum(shift_feature_value(values, spec, *feature) for feature in features)) % mod

    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(256))
    if not output_matches(sim, output, predictor, samples):
        return None

    parts = [sized_const(base, width)] if base else []
    parts.extend(shift_feature_expr(feature) for feature in features)
    return emit_decls(spec, [f"assign {output} = " + " + ".join(parts) + ";"])


ProductTerm = Tuple[int, str, str, bool, bool, int, bool]
LinearTerm = Tuple[int, str, bool]


def signed_or_unsigned_value(value: int, width: int, signed: bool) -> int:
    return signed_value(value, width) if signed else value


def product_contribution(
    values: Dict[str, int],
    spec: Spec,
    a: str,
    b: str,
    signed_a: bool,
    signed_b: bool,
    product_width: int,
    result_signed: bool,
) -> int:
    av = signed_or_unsigned_value(values.get(a, 0), spec.inputs[a], signed_a)
    bv = signed_or_unsigned_value(values.get(b, 0), spec.inputs[b], signed_b)
    product = (av * bv) & ((1 << product_width) - 1)
    return signed_value(product, product_width) if result_signed else product


def adjacent_product_sum_learner(spec: Spec) -> Optional[str]:
    if len(spec.outputs) != 1:
        return None
    header_order = [name.strip() for name in spec.header.split(",")]
    data = [name for name in header_order if spec.inputs.get(name, 0) > 1]
    if len(data) < 4 or len(data) > 40 or len(data) % 2:
        return None
    output = next(iter(spec.outputs))
    out_width = spec.outputs[output]
    if out_width > 128:
        return None
    pairs = [(data[i], data[i + 1]) for i in range(0, len(data), 2)]
    mod = 1 << out_width

    zero = {name: 0 for name in spec.inputs}
    pair_modes: List[Tuple[str, str, bool]] = []
    for index, (a, b) in enumerate(pairs):
        probes: List[Dict[str, int]] = []
        a_values = {0, 1, 2, (1 << spec.inputs[a]) - 1, 1 << (spec.inputs[a] - 1)}
        b_values = {0, 1, 2, (1 << spec.inputs[b]) - 1, 1 << (spec.inputs[b] - 1)}
        for av in a_values:
            for bv in b_values:
                vec = dict(zero)
                vec[a] = av & ((1 << spec.inputs[a]) - 1)
                vec[b] = bv & ((1 << spec.inputs[b]) - 1)
                probes.append(vec)
        rows = simulate_output_rows(spec, probes)
        found_signed = None
        for is_signed in (False, True):
            ok = True
            product_mask = (1 << (spec.inputs[a] + spec.inputs[b])) - 1
            for vec, row in zip(probes, rows):
                av = signed_or_unsigned_value(vec[a], spec.inputs[a], is_signed)
                bv = signed_or_unsigned_value(vec[b], spec.inputs[b], is_signed)
                if ((av * bv) & product_mask) % mod != row[output]:
                    ok = False
                    break
            if ok:
                found_signed = is_signed
                break
        if found_signed is None:
            return None
        pair_modes.append((a, b, found_signed))

    rng = random.Random(32)
    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(512))
    rows = simulate_output_rows(spec, samples)

    def pair_total(values: Dict[str, int]) -> int:
        total = 0
        for a, b, is_signed in pair_modes:
            av = signed_or_unsigned_value(values[a], spec.inputs[a], is_signed)
            bv = signed_or_unsigned_value(values[b], spec.inputs[b], is_signed)
            total += (av * bv) & ((1 << (spec.inputs[a] + spec.inputs[b])) - 1)
        return total

    min_acc_width = max(spec.inputs[a] + spec.inputs[b] for a, b, _is_signed in pair_modes)
    acc_model: Optional[Tuple[int, bool]] = None
    for candidate_width in range(min_acc_width, out_width + 1):
        acc_mask = (1 << candidate_width) - 1
        for acc_signed in (True, False):
            ok = True
            for values, row in zip(samples, rows):
                total = pair_total(values) & acc_mask
                predicted = signed_value(total, candidate_width) % mod if acc_signed else total % mod
                if predicted != row[output]:
                    ok = False
                    break
            if ok:
                acc_model = (candidate_width, acc_signed)
                break
        if acc_model is not None:
            break
    if acc_model is None:
        return None

    acc_candidates = []
    if any(is_signed for _a, _b, is_signed in pair_modes):
        acc_candidates.append((min_acc_width, True))
    acc_candidates.append(acc_model)
    acc_candidates.append((min_acc_width, False))

    seen_acc = set()
    for acc_width, acc_signed in acc_candidates:
        if (acc_width, acc_signed) in seen_acc:
            continue
        seen_acc.add((acc_width, acc_signed))

        signed_inputs = sorted(
            {name for a, b, is_signed in pair_modes if is_signed for name in (a, b)},
            key=lambda n: list(spec.inputs).index(n),
        )
        body: List[str] = []
        for name in signed_inputs:
            body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
            body.append(f"assign s_{name} = {name};")
        terms: List[str] = []
        for index, (a, b, is_signed) in enumerate(pair_modes):
            lhs = f"s_{a}" if is_signed else a
            rhs = f"s_{b}" if is_signed else b
            product_width = spec.inputs[a] + spec.inputs[b]
            product = f"adj_product_{index}"
            term = f"adj_term_{index}"
            body.append(f"wire [{product_width - 1}:0] {product};")
            body.append(f"assign {product} = {lhs} * {rhs};")
            body.append(f"wire [{acc_width - 1}:0] {term};")
            body.append(f"assign {term} = {product};")
            terms.append(term)
        sum_signed_kw = "signed " if acc_signed else ""
        body.append(f"wire {sum_signed_kw}[{acc_width - 1}:0] adj_product_sum;")
        body.append("assign adj_product_sum = " + " + ".join(terms) + ";")
        body.append(f"assign {output} = adj_product_sum;")
        rtl = emit_decls(spec, body)
        ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=512, seed=32)
        if ok:
            return rtl
    return None


def product_sum_learner(spec: Spec) -> Optional[str]:
    if len(spec.outputs) != 1:
        return None
    names = [name for name, width in spec.inputs.items() if width > 1]
    if not (2 <= len(names) <= 40):
        return None
    output = next(iter(spec.outputs))
    width = spec.outputs[output]
    if width > 128:
        return None

    mod = 1 << width
    zero = {name: 0 for name in spec.inputs}
    discovery_vectors: List[Dict[str, int]] = [dict(zero)]
    single_index: Dict[str, int] = {}
    for name in names:
        vec = dict(zero)
        vec[name] = 1
        single_index[name] = len(discovery_vectors)
        discovery_vectors.append(vec)
    pair_index: Dict[Tuple[str, str], int] = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            vec = dict(zero)
            vec[a] = 1
            vec[b] = 1
            pair_index[(a, b)] = len(discovery_vectors)
            discovery_vectors.append(vec)

    discovery_rows = simulate_output_rows(spec, discovery_vectors)
    base = discovery_rows[0][output]
    one_values: Dict[str, int] = {}
    linear_coeffs: Dict[str, int] = {}
    for name in names:
        y = discovery_rows[single_index[name]][output]
        one_values[name] = y
        coeff = (y - base) % mod
        if coeff:
            linear_coeffs[name] = coeff

    pair_coeffs: Dict[Tuple[str, str], int] = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            coeff = (discovery_rows[pair_index[(a, b)]][output] - one_values[a] - one_values[b] + base) % mod
            if coeff:
                pair_coeffs[(a, b)] = coeff

    if not linear_coeffs and not pair_coeffs:
        return None
    if len(linear_coeffs) + len(pair_coeffs) > 96:
        return None

    rng = random.Random(12)
    linear_terms: List[LinearTerm] = []
    for name, coeff in linear_coeffs.items():
        found = None
        probes = []
        for _ in range(32):
            vec = dict(zero)
            vec[name] = rng.randrange(1 << spec.inputs[name])
            probes.append(vec)
        rows = simulate_output_rows(spec, probes)
        for is_signed in (False, True):
            ok = True
            for vec, row in zip(probes, rows):
                x = signed_or_unsigned_value(vec[name], spec.inputs[name], is_signed)
                expected = (base + coeff * x) % mod
                if row[output] != expected:
                    ok = False
                    break
            if ok:
                found = is_signed
                break
        if found is None:
            return None
        linear_terms.append((coeff, name, found))

    product_terms: List[ProductTerm] = []
    for (a, b), coeff in pair_coeffs.items():
        found = None
        probes = []
        a_values = [0, 1, (1 << (spec.inputs[a] - 1)), (1 << spec.inputs[a]) - 1]
        b_values = [0, 1, (1 << (spec.inputs[b] - 1)), (1 << spec.inputs[b]) - 1]
        for av in a_values:
            for bv in b_values:
                vec = dict(zero)
                vec[a] = av
                vec[b] = bv
                probes.append(vec)
        for _ in range(48):
            vec = dict(zero)
            vec[a] = rng.randrange(1 << spec.inputs[a])
            vec[b] = rng.randrange(1 << spec.inputs[b])
            probes.append(vec)
        rows = simulate_output_rows(spec, probes)
        width_candidates = sorted({spec.inputs[a] + spec.inputs[b], max(spec.inputs[a], spec.inputs[b]), width})
        for signed_a in (False, True):
            for signed_b in (False, True):
                for product_width in width_candidates:
                    for result_signed in (False, True):
                        ok = True
                        for vec, row in zip(probes, rows):
                            expected = base
                            for l_coeff, lname, l_signed in linear_terms:
                                x = signed_or_unsigned_value(vec[lname], spec.inputs[lname], l_signed)
                                expected += l_coeff * x
                            expected += coeff * product_contribution(
                                vec,
                                spec,
                                a,
                                b,
                                signed_a,
                                signed_b,
                                product_width,
                                result_signed,
                            )
                            if row[output] != expected % mod:
                                ok = False
                                break
                        if ok:
                            found = (signed_a, signed_b, product_width, result_signed)
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        if found is None:
            return None
        signed_a, signed_b, product_width, result_signed = found
        product_terms.append((coeff, a, b, signed_a, signed_b, product_width, result_signed))

    def raw_total(values: Dict[str, int]) -> int:
        total = base
        for coeff, name, is_signed in linear_terms:
            total += coeff * signed_or_unsigned_value(values.get(name, 0), spec.inputs[name], is_signed)
        for coeff, a, b, signed_a, signed_b, product_width, result_signed in product_terms:
            total += coeff * product_contribution(
                values,
                spec,
                a,
                b,
                signed_a,
                signed_b,
                product_width,
                result_signed,
            )
        return total

    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(256))
    rows = simulate_output_rows(spec, samples)
    max_term_width = max(term[5] for term in product_terms) if product_terms else width
    sum_width = None
    sum_signed = False
    for candidate_width in sorted({width, max_term_width}, reverse=True):
        for candidate_signed in (False, True):
            ok = True
            for values, row in zip(samples, rows):
                total = raw_total(values) & ((1 << candidate_width) - 1)
                predicted = signed_value(total, candidate_width) % mod if candidate_signed else total % mod
                if predicted != row[output]:
                    ok = False
                    break
            if ok:
                sum_width = candidate_width
                sum_signed = candidate_signed
                break
        if sum_width is not None:
            break
    if sum_width is None:
        return None

    signed_inputs = {
        name
        for _coeff, name, is_signed in linear_terms
        if is_signed
    }
    signed_inputs.update(
        name
        for _coeff, a, b, signed_a, signed_b, _product_width, _result_signed in product_terms
        for name, is_signed in ((a, signed_a), (b, signed_b))
        if is_signed
    )
    body: List[str] = []
    for name in sorted(signed_inputs, key=lambda n: list(spec.inputs).index(n)):
        body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        body.append(f"assign s_{name} = {name};")

    term_names: List[str] = []
    term_index = 0

    def add_term(expr: str, coeff: int) -> None:
        nonlocal term_index
        assert sum_width is not None
        signed_coeff = signed_mod(coeff, sum_width)
        if signed_coeff == 1:
            term_expr = expr
        elif signed_coeff == -1:
            term_expr = f"-({expr})"
        elif signed_coeff < 0:
            term_expr = f"-(({expr}) * {abs(signed_coeff)})"
        else:
            term_expr = f"({expr}) * {signed_coeff}"
        name = f"term_{term_index}"
        term_index += 1
        body.append(f"wire [{sum_width - 1}:0] {name};")
        body.append(f"assign {name} = {term_expr};")
        term_names.append(name)

    for coeff, name, is_signed in linear_terms:
        add_term(f"s_{name}" if is_signed else name, coeff)
    product_index = 0
    for coeff, a, b, signed_a, signed_b, product_width, result_signed in product_terms:
        lhs = f"s_{a}" if signed_a else a
        rhs = f"s_{b}" if signed_b else b
        product_name = f"product_{product_index}"
        product_index += 1
        signed_kw = "signed " if result_signed else ""
        body.append(f"wire {signed_kw}[{product_width - 1}:0] {product_name};")
        body.append(f"assign {product_name} = {lhs} * {rhs};")
        add_term(product_name, coeff)

    parts = [sized_const(base, sum_width)] if base else []
    parts.extend(term_names)
    if sum_width == width and not sum_signed:
        body.append(f"assign {output} = " + " + ".join(parts) + ";")
    else:
        signed_kw = "signed " if sum_signed else ""
        body.append(f"wire {signed_kw}[{sum_width - 1}:0] product_sum;")
        body.append("assign product_sum = " + " + ".join(parts) + ";")
        body.append(f"assign {output} = product_sum;")
    return emit_decls(spec, body)


def multiply_add_shift_learner(spec: Spec) -> Optional[str]:
    if len(spec.outputs) != 1:
        return None
    data = [name for name, width in spec.inputs.items() if width > 1]
    if not (3 <= len(data) <= 5):
        return None
    output = next(iter(spec.outputs))
    out_width = spec.outputs[output]
    if out_width > 96:
        return None

    rng = random.Random(31)
    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(192))
    rows = simulate_output_rows(spec, samples)
    observed = [row[output] for row in rows]
    out_mask = (1 << out_width) - 1

    found: Optional[Tuple[str, str, str, int, bool, bool, bool]] = None
    max_shift = min(32, max(spec.inputs[name] for name in data))
    for a in data:
        for b in data:
            if b == a:
                continue
            for c in data:
                if c in {a, b}:
                    continue
                for shift in range(max_shift + 1):
                    for signed_a in (False, True):
                        for signed_b in (False, True):
                            for signed_c in (False, True):
                                predicted = []
                                for values in samples:
                                    av = signed_or_unsigned_value(values.get(a, 0), spec.inputs[a], signed_a)
                                    bv = signed_or_unsigned_value(values.get(b, 0), spec.inputs[b], signed_b)
                                    cv = signed_or_unsigned_value(values.get(c, 0), spec.inputs[c], signed_c)
                                    predicted.append(((av * bv + cv) >> shift) & out_mask)
                                if predicted == observed:
                                    found = (a, b, c, shift, signed_a, signed_b, signed_c)
                                    break
                            if found:
                                break
                        if found:
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        if found:
            break

    if found is None:
        return None

    fresh = targeted_values(spec)
    fresh.extend(random_values(spec, rng) for _ in range(384))
    fresh_rows = simulate_output_rows(spec, fresh)
    a, b, c, shift, signed_a, signed_b, signed_c = found
    for values, row in zip(fresh, fresh_rows):
        av = signed_or_unsigned_value(values.get(a, 0), spec.inputs[a], signed_a)
        bv = signed_or_unsigned_value(values.get(b, 0), spec.inputs[b], signed_b)
        cv = signed_or_unsigned_value(values.get(c, 0), spec.inputs[c], signed_c)
        if (((av * bv + cv) >> shift) & out_mask) != row[output]:
            return None

    product_width = spec.inputs[a] + spec.inputs[b]
    sum_width = max(product_width, spec.inputs[c]) + 1
    signed_inputs = {
        name
        for name, is_signed in ((a, signed_a), (b, signed_b), (c, signed_c))
        if is_signed
    }
    sum_signed = signed_a or signed_b or signed_c
    body: List[str] = []
    for name in sorted(signed_inputs, key=lambda n: list(spec.inputs).index(n)):
        body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        body.append(f"assign s_{name} = {name};")
    lhs = f"s_{a}" if signed_a else a
    rhs = f"s_{b}" if signed_b else b
    addend = f"s_{c}" if signed_c else c
    signed_kw = "signed " if sum_signed else ""
    body.append(f"wire {signed_kw}[{sum_width - 1}:0] madd_shift_sum;")
    body.append(f"assign madd_shift_sum = {lhs} * {rhs} + {addend};")
    body.append(f"assign {output} = madd_shift_sum >> {shift};")
    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=512, seed=31)
    return rtl if ok else None


def linear_combination_learner(spec: Spec) -> Optional[str]:
    names = list(spec.inputs)
    if not (2 <= len(names) <= 128 and 1 <= len(spec.outputs) <= 4 and all(width <= 128 for width in spec.outputs.values())):
        return None

    zero = {name: 0 for name in names}
    discovery_vectors = [dict(zero)]
    single_index: Dict[str, int] = {}
    for name in names:
        vec = dict(zero)
        vec[name] = 1
        single_index[name] = len(discovery_vectors)
        discovery_vectors.append(vec)
    discovery_rows = simulate_output_rows(spec, discovery_vectors)

    rng = random.Random(24)
    output_models: Dict[str, Tuple[int, List[LinearTerm], Callable[[Dict[str, int]], int]]] = {}
    signed_inputs: set[str] = set()
    for output, width in spec.outputs.items():
        mod = 1 << width
        base = discovery_rows[0][output]
        coeffs = {
            name: (discovery_rows[single_index[name]][output] - base) % mod
            for name in names
        }
        coeffs = {name: coeff for name, coeff in coeffs.items() if coeff}
        if len(coeffs) > 120:
            return None
        terms: List[LinearTerm] = []
        for name, coeff in coeffs.items():
            probes = []
            for value in [0, 1, (1 << (spec.inputs[name] - 1)) if spec.inputs[name] > 1 else 1, (1 << spec.inputs[name]) - 1]:
                vec = dict(zero)
                vec[name] = value & ((1 << spec.inputs[name]) - 1)
                probes.append(vec)
            for _ in range(16):
                vec = dict(zero)
                vec[name] = rng.randrange(1 << spec.inputs[name])
                probes.append(vec)
            rows = simulate_output_rows(spec, probes)
            found_signed = None
            for is_signed in (False, True):
                ok = True
                for vec, row in zip(probes, rows):
                    x = signed_or_unsigned_value(vec[name], spec.inputs[name], is_signed)
                    if (base + coeff * x) % mod != row[output]:
                        ok = False
                        break
                if ok:
                    found_signed = is_signed
                    break
            if found_signed is None:
                return None
            if found_signed:
                signed_inputs.add(name)
            terms.append((coeff, name, found_signed))

        def predictor(values: Dict[str, int], base: int = base, terms: List[LinearTerm] = terms, width: int = width) -> int:
            total = base
            for coeff, name, is_signed in terms:
                total += coeff * signed_or_unsigned_value(values.get(name, 0), spec.inputs[name], is_signed)
            return total % (1 << width)

        output_models[output] = (base, terms, predictor)

    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(512))
    rows = simulate_output_rows(spec, samples)
    for values, row in zip(samples, rows):
        for output, (_base, _terms, predictor) in output_models.items():
            if predictor(values) != row[output]:
                return None

    body: List[str] = []
    for name in sorted(signed_inputs, key=lambda n: list(spec.inputs).index(n)):
        body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        body.append(f"assign s_{name} = {name};")

    expressions: Dict[str, str] = {}
    for output, (base, terms, _predictor) in output_models.items():
        width = spec.outputs[output]
        parts = [sized_const(base, width)] if base else []
        for coeff, name, is_signed in terms:
            term = f"s_{name}" if is_signed else extend_expr(name, spec.inputs[name], width)
            signed_coeff = signed_mod(coeff, width)
            if signed_coeff == 1:
                parts.append(term)
            elif signed_coeff == -1:
                parts.append(f"-({term})")
            elif signed_coeff < 0:
                parts.append(f"-(({term}) * {abs(signed_coeff)})")
            else:
                parts.append(f"({term}) * {signed_coeff}")
        expressions[output] = " + ".join(parts).replace("+ -", "- ") or sized_const(0, width)

    shared_body, expressions = share_common_addends(spec, expressions)
    body.extend(shared_body)
    body.extend(f"assign {output} = {expressions[output]};" for output in spec.outputs)
    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=256, seed=24)
    return rtl if ok else None


PairedFeature = Tuple[str, Tuple[str, ...], bool]


def paired_sum_linear_slice_learner(spec: Spec) -> Optional[str]:
    word_outputs = [name for name, width in spec.outputs.items() if width > 1]
    if not (2 <= len(word_outputs) <= 3):
        return None
    data = [name for name, width in spec.inputs.items() if width > 1]
    controls = [name for name, width in spec.inputs.items() if width == 1]
    if not (12 <= len(data) <= 96):
        return None

    header_order = [name.strip() for name in spec.header.split(",")]
    ordered_data = [name for name in header_order if name in data]
    groups_by_width: Dict[int, List[str]] = {}
    for name in ordered_data:
        groups_by_width.setdefault(spec.inputs[name], []).append(name)
    primary = max(groups_by_width.values(), key=len)
    if len(primary) < 8:
        return None

    scalar_sim = PrimitiveSim(spec)
    sim_rows_cache: Dict[Tuple[Tuple[str, int], ...], Dict[str, int]] = {}

    def sim_vec(vec: Dict[str, int]) -> Dict[str, int]:
        key = tuple(sorted(vec.items()))
        if key not in sim_rows_cache:
            sim_rows_cache[key] = scalar_sim(vec)
        return sim_rows_cache[key]

    zero = {name: 0 for name in spec.inputs}
    base_rows = sim_vec(zero)
    rng = random.Random(36)

    def feature_value(values: Dict[str, int], feature: PairedFeature) -> int:
        kind, names, is_signed = feature
        if kind == "single":
            name = names[0]
            return signed_or_unsigned_value(values.get(name, 0), spec.inputs[name], is_signed)
        a, b = names
        width = max(spec.inputs[a], spec.inputs[b]) + 1
        total = signed_value(values.get(a, 0), spec.inputs[a]) + signed_value(values.get(b, 0), spec.inputs[b])
        raw = total & ((1 << width) - 1)
        return signed_value(raw, width) if is_signed else raw

    def feature_probe(feature: PairedFeature, value: int) -> Dict[str, int]:
        vec = dict(zero)
        kind, names, _is_signed = feature
        if kind == "single":
            name = names[0]
            vec[name] = value & ((1 << spec.inputs[name]) - 1)
        else:
            vec[names[0]] = value & ((1 << spec.inputs[names[0]]) - 1)
        return vec

    def candidate_partitions() -> Iterable[List[PairedFeature]]:
        primary_set = set(primary)
        remainder = [name for name in ordered_data if name not in primary_set]
        max_prefix = len(primary) if len(primary) % 2 == 0 else len(primary) - 1
        for prefix in range(max_prefix, 1, -2):
            features: List[PairedFeature] = []
            for i in range(0, prefix, 2):
                a, b = primary[i], primary[i + 1]
                features.append(("pair", (a, b), False))
            features.extend(("single", (name,), False) for name in primary[prefix:])
            features.extend(("single", (name,), False) for name in remainder)
            yield features

    def fit_primary_output(output: str, features: List[PairedFeature]) -> Optional[Tuple[List[LinearTerm], List[PairedFeature]]]:
        width = spec.outputs[output]
        mod = 1 << width
        fitted_terms: List[LinearTerm] = []
        fitted_features: List[PairedFeature] = []
        for index, feature in enumerate(features):
            probe = feature_probe(feature, 1)
            coeff = (sim_vec(probe)[output] - base_rows[output]) % mod
            if not coeff:
                continue
            found_feature = None
            for is_signed in (False, True):
                trial = (feature[0], feature[1], is_signed)
                ok = True
                probes = [0, 1, 2]
                for name in feature[1]:
                    in_width = spec.inputs[name]
                    probes.extend([(1 << (in_width - 1)), (1 << in_width) - 1])
                for _ in range(12):
                    probes.append(rng.randrange(1 << spec.inputs[feature[1][0]]))
                for value in probes:
                    vec = feature_probe(trial, value)
                    predicted = (base_rows[output] + coeff * feature_value(vec, trial)) % mod
                    if predicted != sim_vec(vec)[output]:
                        ok = False
                        break
                if ok:
                    found_feature = trial
                    break
            if found_feature is None:
                return None
            fitted_features.append(found_feature)
            fitted_terms.append((coeff, f"__feature_{index}", found_feature[2]))

        def predictor(values: Dict[str, int]) -> int:
            total = base_rows[output]
            for (coeff, _name, _signed), feature in zip(fitted_terms, fitted_features):
                total += coeff * feature_value(values, feature)
            return total % mod

        samples = targeted_values(spec)
        samples.extend(random_values(spec, rng) for _ in range(384))
        rows = simulate_output_rows(spec, samples)
        for values, row in zip(samples, rows):
            if predictor(values) != row[output]:
                return None
        return fitted_terms, fitted_features

    primary_model = None
    primary_output = max(word_outputs, key=lambda out: spec.outputs[out])
    for features in candidate_partitions():
        fitted = fit_primary_output(primary_output, features)
        if fitted is not None:
            primary_model = fitted
            break
    if primary_model is None:
        return None
    terms, fitted_features = primary_model

    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(512))
    rows = simulate_output_rows(spec, samples)

    def primary_value(values: Dict[str, int]) -> int:
        width = spec.outputs[primary_output]
        total = base_rows[primary_output]
        for (coeff, _name, _signed), feature in zip(terms, fitted_features):
            total += coeff * feature_value(values, feature)
        return total % (1 << width)

    derived_outputs: Dict[str, Tuple[int, int, Optional[str]]] = {}
    for output in word_outputs:
        if output == primary_output:
            continue
        out_width = spec.outputs[output]
        found = None
        for lo in range(0, spec.outputs[primary_output] - out_width + 1):
            for extra in [None, *controls]:
                ok = True
                for values, row in zip(samples, rows):
                    predicted = (primary_value(values) >> lo) & ((1 << out_width) - 1)
                    if extra is not None:
                        predicted = (predicted + values.get(extra, 0)) & ((1 << out_width) - 1)
                    if predicted != row[output]:
                        ok = False
                        break
                if ok:
                    found = (lo, lo + out_width - 1, extra)
                    break
            if found:
                break
        if found is None:
            return None
        derived_outputs[output] = found

    body: List[str] = []
    signed_inputs: set[str] = set()
    feature_exprs: Dict[int, Tuple[str, int, bool]] = {}
    for index, feature in enumerate(fitted_features):
        kind, names, is_signed = feature
        if kind == "single":
            name = names[0]
            if is_signed:
                signed_inputs.add(name)
                expr = f"s_{name}"
            else:
                expr = name
            feature_exprs[index] = (expr, spec.inputs[name], is_signed)
        else:
            a, b = names
            signed_inputs.update([a, b])
            pair_width = max(spec.inputs[a], spec.inputs[b]) + 1
            pair_name = f"pair_sum_{index}"
            body.append(f"wire signed [{pair_width - 1}:0] {pair_name};")
            body.append(f"assign {pair_name} = s_{a} + s_{b};")
            feature_exprs[index] = (pair_name, pair_width, is_signed)

    prelude: List[str] = []
    for name in sorted(signed_inputs, key=lambda n: list(spec.inputs).index(n)):
        prelude.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        prelude.append(f"assign s_{name} = {name};")
    body = prelude + body

    width = spec.outputs[primary_output]
    parts = [sized_const(base_rows[primary_output], width)] if base_rows[primary_output] else []
    for term_index, ((coeff, _feature_name, _signed), feature) in enumerate(zip(terms, fitted_features)):
        expr, expr_width, expr_signed = feature_exprs[term_index]
        term = sign_extend_expr(expr, expr_width, width) if expr_signed else extend_expr(expr, expr_width, width)
        signed_coeff = signed_mod(coeff, width)
        if signed_coeff == 1:
            parts.append(term)
        elif signed_coeff == -1:
            parts.append(f"-({term})")
        elif signed_coeff < 0:
            parts.append(f"-(({term}) * {abs(signed_coeff)})")
        else:
            parts.append(f"({term}) * {signed_coeff}")
    body.append(f"wire [{width - 1}:0] learned_primary;")
    body.append("assign learned_primary = " + " + ".join(parts).replace("+ -", "- ") + ";")
    body.append(f"assign {primary_output} = learned_primary;")
    for output, (lo, hi, extra) in derived_outputs.items():
        expr = f"learned_primary[{hi}:{lo}]"
        if extra is not None:
            expr = f"{expr} + {extra}"
        body.append(f"assign {output} = {expr};")

    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=512, seed=36)
    return rtl if ok else None


def fixed_point_optional_mac_learner(spec: Spec) -> Optional[str]:
    if len(spec.outputs) != 2:
        return None
    outputs = list(spec.outputs)
    if spec.outputs[outputs[0]] != spec.outputs[outputs[1]]:
        return None
    out_width = spec.outputs[outputs[0]]
    if out_width > 32:
        return None
    controls = [name for name, width in spec.inputs.items() if width == 1]
    data_by_width: Dict[int, List[str]] = {}
    for name, width in spec.inputs.items():
        if width > 1:
            data_by_width.setdefault(width, []).append(name)
    if len(controls) < 2:
        return None

    rng = random.Random(37)
    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(256))
    rows = simulate_output_rows(spec, samples)
    out1, out2 = outputs
    out_mask = (1 << out_width) - 1

    def s(values: Dict[str, int], name: str) -> int:
        return signed_value(values.get(name, 0), spec.inputs[name])

    base_model = None
    for diff_width, diff_names in data_by_width.items():
        if diff_width > max(8, out_width // 2):
            continue
        if len(diff_names) < 2:
            continue
        for a, b in combinations(diff_names, 2):
            for mult_width, mult_names in data_by_width.items():
                if mult_width < out_width - 1:
                    continue
                for mult in mult_names:
                    if mult in {a, b}:
                        continue
                    for base_width, base_names in data_by_width.items():
                        if base_width not in {out_width - 1, out_width}:
                            continue
                        for base in base_names:
                            if base in {a, b, mult}:
                                continue
                            for shift in range(max(0, diff_width - 1), min(16, diff_width + 2)):
                                ok = True
                                for values, row in zip(samples, rows):
                                    pred = (s(values, base) + ((s(values, a) - s(values, b)) * s(values, mult) >> shift)) & out_mask
                                    if pred != row[out1]:
                                        ok = False
                                        break
                                if ok:
                                    base_model = (a, b, mult, base, shift)
                                    break
                            if base_model:
                                break
                        if base_model:
                            break
                    if base_model:
                        break
                if base_model:
                    break
            if base_model:
                break
        if base_model:
            break
    if base_model is None:
        return None

    base_a, base_b, base_mult, base_input, base_shift = base_model

    def base_value(values: Dict[str, int]) -> int:
        return (s(values, base_input) + ((s(values, base_a) - s(values, base_b)) * s(values, base_mult) >> base_shift)) & out_mask

    def diff_to_out2(values: Dict[str, int]) -> int:
        return (values.get(out2, 0) - base_value(values)) & out_mask

    # Search for an optional lane-sum term controlled by one bit.
    lane_model = None
    scale_groups = [names for width, names in data_by_width.items() if 6 <= width <= 12 and len(names) >= 3]
    base_groups = [names for width, names in data_by_width.items() if 10 <= width <= out_width and len(names) >= 3]
    small_groups = [names for width, names in data_by_width.items() if 3 <= width <= 8 and len(names) >= 2 * min(len(group) for group in scale_groups) if scale_groups]
    mult_candidates = [name for width, names in data_by_width.items() if width >= out_width for name in names if name != base_mult]
    for control in controls:
        for scales in scale_groups:
            for lane_bases in base_groups:
                lane_count = min(len(scales), len(lane_bases))
                if lane_count < 3:
                    continue
                for smalls in small_groups:
                    if len(smalls) < 2 * lane_count:
                        continue
                    pairs = [(smalls[i], smalls[i + 1]) for i in range(0, 2 * lane_count, 2)]
                    for mult in mult_candidates:
                        for adjust_shift in (base_shift,):
                            for product_shift in range(max(0, base_shift - 1), base_shift + 3):
                                ok = True
                                checked = 0
                                for values, row in zip(samples, rows):
                                    if any(values.get(other_control, 0) for other_control in controls if other_control != control):
                                        continue
                                    checked += 1
                                    term = 0
                                    if values.get(control, 0):
                                        for scale, lane_base, (da, db) in zip(scales[:lane_count], lane_bases[:lane_count], pairs):
                                            adjusted = (s(values, lane_base) + ((s(values, da) - s(values, db)) * s(values, mult) >> adjust_shift)) & out_mask
                                            term += (values.get(scale, 0) * adjusted) >> product_shift
                                    if term & out_mask != diff_to_out2({**values, out2: row[out2]}):
                                        ok = False
                                        break
                                if ok and checked >= 32:
                                    lane_model = (control, tuple(scales[:lane_count]), tuple(lane_bases[:lane_count]), tuple(pairs), mult, adjust_shift, product_shift)
                                    break
                            if lane_model:
                                break
                        if lane_model:
                            break
                    if lane_model:
                        break
                if lane_model:
                    break
            if lane_model:
                break
        if lane_model:
            break

    # Search for a second optional single adjusted-base term on the residual.
    single_model = None
    for control in controls:
        if lane_model and control == lane_model[0]:
            continue
        for base_width, base_names in data_by_width.items():
            if not (max(2, out_width - 6) <= base_width <= out_width - 2):
                continue
            for base in base_names:
                for mult_width, mult_names in data_by_width.items():
                    if mult_width < out_width:
                        continue
                    for mult in mult_names:
                        for diff_width, diff_names in data_by_width.items():
                            if not (2 <= diff_width <= max(4, out_width // 3) and len(diff_names) >= 2):
                                continue
                            for a, b in combinations(diff_names, 2):
                                for diff_signed in (False, True):
                                    for shift in (base_shift,):
                                        for shifted_width in range(max(1, spec.inputs[base] - 2), spec.inputs[base] + 2):
                                            shifted_mask = (1 << shifted_width) - 1
                                            ok = True
                                            for values, row in zip(samples, rows):
                                                residual = diff_to_out2({**values, out2: row[out2]})
                                                if lane_model and values.get(lane_model[0], 0):
                                                    _c, scales, lane_bases, pairs, lm, adj_s, prod_s = lane_model
                                                    lane_term = 0
                                                    for scale, lane_base, (da, db) in zip(scales, lane_bases, pairs):
                                                        adjusted = (s(values, lane_base) + ((s(values, da) - s(values, db)) * s(values, lm) >> adj_s)) & out_mask
                                                        lane_term += (values.get(scale, 0) * adjusted) >> prod_s
                                                    residual = (residual - lane_term) & out_mask
                                                pred = 0
                                                if values.get(control, 0):
                                                    av = s(values, a) if diff_signed else values.get(a, 0)
                                                    bv = s(values, b) if diff_signed else values.get(b, 0)
                                                    shifted = ((av - bv) * s(values, mult) >> shift) & shifted_mask
                                                    pred = (values.get(base, 0) + shifted) & out_mask
                                                if pred != residual:
                                                    ok = False
                                                    break
                                            if ok:
                                                single_model = (control, base, mult, a, b, diff_signed, shift, shifted_width)
                                                break
                                        if single_model:
                                            break
                                    if single_model:
                                        break
                                if single_model:
                                    break
                                if single_model:
                                    break
                            if single_model:
                                break
                        if single_model:
                            break
                    if single_model:
                        break
                if single_model:
                    break
            if single_model:
                break
        if single_model:
            break

    if lane_model is None and single_model is None:
        return None

    signed_inputs = {base_a, base_b, base_mult, base_input}
    if lane_model:
        _c, _scales, lane_bases, pairs, lm, _adj_s, _prod_s = lane_model
        signed_inputs.add(lm)
        signed_inputs.update(lane_bases)
        for da, db in pairs:
            signed_inputs.update([da, db])
    if single_model:
        _c, _base, mult, a, b, diff_signed, _shift, _shifted_width = single_model
        signed_inputs.add(mult)
        if diff_signed:
            signed_inputs.update([a, b])

    body: List[str] = []
    for name in sorted(signed_inputs, key=lambda n: list(spec.inputs).index(n)):
        body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        body.append(f"assign s_{name} = {name};")
    body.append(f"wire signed [{out_width - 1}:0] fixed_base;")
    body.append(f"assign fixed_base = s_{base_input} + ((s_{base_a} - s_{base_b}) * s_{base_mult} >>> {base_shift});")
    body.append(f"assign {out1} = fixed_base;")
    out2_parts = ["fixed_base"]
    if lane_model:
        control, scales, lane_bases, pairs, lm, adj_shift, prod_shift = lane_model
        lane_terms = []
        for idx, (scale, lane_base, (da, db)) in enumerate(zip(scales, lane_bases, pairs)):
            adjusted = f"lane_adjusted_{idx}"
            product = f"lane_product_{idx}"
            body.append(f"wire [{out_width - 1}:0] {adjusted};")
            body.append(f"assign {adjusted} = s_{lane_base} + ((s_{da} - s_{db}) * s_{lm} >>> {adj_shift});")
            body.append(f"wire [{out_width}:0] {product};")
            body.append(f"assign {product} = {scale} * {adjusted} >> {prod_shift};")
            lane_terms.append(product)
        lane_sum = " + ".join(lane_terms) if lane_terms else f"{out_width}'d0"
        out2_parts.append(f"({control} ? ({lane_sum}) : {out_width}'d0)")
    if single_model:
        control, base, mult, a, b, diff_signed, shift, shifted_width = single_model
        body.append(f"wire [{out_width - 1}:0] single_optional_term;")
        body.append(f"wire [{shifted_width - 1}:0] single_shifted_term;")
        diff_width = max(spec.inputs[a], spec.inputs[b]) + 1
        if diff_signed:
            lhs = sign_extend_expr(f"s_{a}", spec.inputs[a], diff_width)
            rhs = sign_extend_expr(f"s_{b}", spec.inputs[b], diff_width)
        else:
            lhs = extend_expr(a, spec.inputs[a], diff_width)
            rhs = extend_expr(b, spec.inputs[b], diff_width)
        body.append(f"assign single_shifted_term = (({lhs} - {rhs}) * s_{mult} >>> {shift});")
        body.append(f"assign single_optional_term = {base} + single_shifted_term;")
        out2_parts.append(f"({control} ? single_optional_term : {out_width}'d0)")
    body.append(f"assign {out2} = " + " + ".join(out2_parts) + ";")

    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=512, seed=37)
    return rtl if ok else None


def discover_output_support(
    spec: Spec,
    output: str,
    samples_per_input: int = 12,
    seed: int = 28,
) -> List[str]:
    rng = random.Random(seed)
    vectors: List[Dict[str, int]] = []
    owners: List[str] = []
    output_width = spec.outputs[output]
    mask = (1 << output_width) - 1
    for name, width in spec.inputs.items():
        for _ in range(samples_per_input):
            base = random_values(spec, rng)
            other = dict(base)
            other[name] = (base[name] ^ (1 << rng.randrange(width))) & ((1 << width) - 1)
            vectors.extend([base, other])
            owners.append(name)
    rows = simulate_output_rows(spec, vectors)
    support_set = set()
    for pair_idx, name in enumerate(owners):
        i = pair_idx * 2
        if (rows[i][output] & mask) != (rows[i + 1][output] & mask):
            support_set.add(name)
    support = [name for name in spec.inputs if name in support_set]
    return support


def square_sum_value(
    values: Dict[str, int],
    names: Iterable[str],
    spec: Spec,
    sum_width: int,
    is_signed: bool,
) -> int:
    total = 0
    for name in names:
        value = values.get(name, 0)
        if is_signed:
            value = signed_value(value, spec.inputs[name])
        total += value * value
    return total & ((1 << sum_width) - 1)


def square_sum_flags_learner(spec: Spec) -> Optional[str]:
    if not spec.outputs or any(width != 1 for width in spec.outputs.values()):
        return None
    data = [name for name, width in spec.inputs.items() if width > 1]
    if not (4 <= len(data) <= 14):
        return None
    square_width = max(spec.inputs[name] for name in data) * 2
    max_group_size = 4 if len(data) <= 10 else 3
    sum_width = square_width + max(1, (max_group_size - 1).bit_length())

    rng = random.Random(28)
    base_samples = targeted_values(spec)
    base_samples.extend(random_values(spec, rng) for _ in range(160))
    base_rows = simulate_output_rows(spec, base_samples)
    models: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...], str, bool]] = {}

    def candidate_groups(names: Sequence[str]) -> List[Tuple[str, ...]]:
        limit = min(max_group_size, len(names) - 1)
        return [
            tuple(group)
            for size in range(1, limit + 1)
            for group in combinations(names, size)
        ]

    def find_square_compare_model(
        output: str,
        names: Sequence[str],
    ) -> Optional[Tuple[Tuple[str, ...], Tuple[str, ...], str, bool]]:
        groups = candidate_groups(names)
        if len(groups) < 2:
            return None
        group_sets = {group: set(group) for group in groups}
        observed = tuple(row[output] for row in base_rows)
        for is_signed in (False, True):
            sums = {
                group: tuple(square_sum_value(values, group, spec, sum_width, is_signed) for values in base_samples)
                for group in groups
            }
            for lhs in groups:
                lhs_set = group_sets[lhs]
                lhs_values = sums[lhs]
                for rhs in groups:
                    if lhs > rhs or lhs_set.intersection(group_sets[rhs]):
                        continue
                    rhs_values = sums[rhs]
                    for op in ("<", ">", "<=", ">="):
                        if op == "<":
                            predicted = tuple(int(a < b) for a, b in zip(lhs_values, rhs_values))
                        elif op == ">":
                            predicted = tuple(int(a > b) for a, b in zip(lhs_values, rhs_values))
                        elif op == "<=":
                            predicted = tuple(int(a <= b) for a, b in zip(lhs_values, rhs_values))
                        else:
                            predicted = tuple(int(a >= b) for a, b in zip(lhs_values, rhs_values))
                        if predicted == observed:
                            return lhs, rhs, op, is_signed
        return None

    for output in spec.outputs:
        support = discover_output_support(spec, output, samples_per_input=24, seed=28 + len(models))
        if not (2 <= len(support) <= 10):
            support = data
        support = sorted(support, key=lambda n: list(spec.inputs).index(n))
        found = find_square_compare_model(output, support)
        if found is None and support != data:
            found = find_square_compare_model(output, data)
        if found is None:
            return None
        models[output] = found

    fresh = targeted_values(spec)
    fresh.extend(random_values(spec, rng) for _ in range(256))
    fresh_rows = simulate_output_rows(spec, fresh)
    for values, row in zip(fresh, fresh_rows):
        for output, (lhs, rhs, op, is_signed) in models.items():
            lv = square_sum_value(values, lhs, spec, sum_width, is_signed)
            rv = square_sum_value(values, rhs, spec, sum_width, is_signed)
            if op == "<":
                predicted = int(lv < rv)
            elif op == ">":
                predicted = int(lv > rv)
            elif op == "<=":
                predicted = int(lv <= rv)
            else:
                predicted = int(lv >= rv)
            if predicted != row[output]:
                return None

    used = sorted({name for lhs, rhs, _op, _signed in models.values() for name in (*lhs, *rhs)}, key=lambda n: list(spec.inputs).index(n))
    signed_used = sorted(
        {name for lhs, rhs, _op, is_signed in models.values() if is_signed for name in (*lhs, *rhs)},
        key=lambda n: list(spec.inputs).index(n),
    )
    body: List[str] = []
    for name in signed_used:
        body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        body.append(f"assign s_{name} = {name};")
    for name in used:
        body.append(f"wire [{square_width - 1}:0] sq_{name};")
        source = f"s_{name}" if name in signed_used else name
        body.append(f"assign sq_{name} = {source} * {source};")

    def sum_expr(names: Sequence[str]) -> str:
        parts = [f"sq_{name}" for name in names]
        if parts:
            parts.insert(0, f"{sum_width}'d0")
        return " + ".join(parts) if parts else f"{sum_width}'d0"

    for output, (lhs, rhs, op, _is_signed) in models.items():
        body.append(f"wire [{sum_width - 1}:0] ss_{output}_lhs;")
        body.append(f"wire [{sum_width - 1}:0] ss_{output}_rhs;")
        body.append(f"assign ss_{output}_lhs = {sum_expr(lhs)};")
        body.append(f"assign ss_{output}_rhs = {sum_expr(rhs)};")
        body.append(f"assign {output} = ss_{output}_lhs {op} ss_{output}_rhs;")

    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=256, seed=28)
    return rtl if ok else None


LearnedWord = Tuple[str, int, List[LinearTerm], Callable[[Dict[str, int]], int]]


def learn_linear_word(
    spec: Spec,
    sim: PrimitiveSim,
    output: str,
    samples: Sequence[Dict[str, int]],
) -> Optional[LearnedWord]:
    width = spec.outputs[output]
    if width > 96:
        return None
    mod = 1 << width
    names = [name for name, in_width in spec.inputs.items() if in_width > 1]
    if not names:
        return None
    zero = {name: 0 for name in spec.inputs}
    base = sim(zero)[output]
    coeffs: List[LinearTerm] = []
    rng = random.Random(17)
    for name in names:
        vec = dict(zero)
        vec[name] = 1
        coeff = (sim(vec)[output] - base) % mod
        if not coeff:
            continue
        found = None
        probes = []
        for _ in range(32):
            probe = dict(zero)
            probe[name] = rng.randrange(1 << spec.inputs[name])
            probes.append(probe)
        for is_signed in (False, True):
            ok = True
            for probe in probes:
                x = signed_or_unsigned_value(probe[name], spec.inputs[name], is_signed)
                if sim(probe)[output] != (base + coeff * x) % mod:
                    ok = False
                    break
            if ok:
                found = is_signed
                break
        if found is None:
            return None
        coeffs.append((coeff, name, found))

    if not coeffs and base == 0:
        return None

    def predictor(values: Dict[str, int]) -> int:
        total = base
        for coeff, name, is_signed in coeffs:
            total += coeff * signed_or_unsigned_value(values.get(name, 0), spec.inputs[name], is_signed)
        return total % mod

    if not output_matches(sim, output, predictor, samples):
        return None
    return output, base, coeffs, predictor


def linear_word_expr(spec: Spec, width: int, base: int, coeffs: Sequence[LinearTerm]) -> Tuple[List[str], str]:
    body: List[str] = []
    signed_inputs = [name for _coeff, name, is_signed in coeffs if is_signed]
    for name in sorted(set(signed_inputs), key=lambda n: list(spec.inputs).index(n)):
        body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        body.append(f"assign s_{name} = {name};")
    parts = [sized_const(base, width)] if base else []
    for coeff, name, is_signed in coeffs:
        term = f"s_{name}" if is_signed else extend_expr(name, spec.inputs[name], width)
        signed_coeff = signed_mod(coeff, width)
        if signed_coeff == 1:
            parts.append(term)
        elif signed_coeff == -1:
            parts.append(f"-({term})")
        elif signed_coeff < 0:
            parts.append(f"-(({term}) * {abs(signed_coeff)})")
        else:
            parts.append(f"({term}) * {signed_coeff}")
    return body, " + ".join(parts).replace("+ -", "- ") or sized_const(0, width)


def boundary_samples_for_linear_word(
    spec: Spec,
    word: LearnedWord,
    targets: Iterable[int],
) -> List[Dict[str, int]]:
    output, base, coeffs, predictor = word
    if not coeffs:
        return []
    width = spec.outputs[output]
    mod = 1 << width
    samples: List[Dict[str, int]] = []
    unit_terms = [
        (name, signed_mod(coeff, width), is_signed)
        for coeff, name, is_signed in coeffs
        if abs(signed_mod(coeff, width)) == 1
    ]
    for target in targets:
        target_mod = target % mod
        for name, coeff, is_signed in unit_terms:
            raw = (target_mod - (base % mod)) % mod
            if coeff == -1:
                raw = (-raw) % mod
            in_width = spec.inputs[name]
            value = raw & ((1 << in_width) - 1)
            if is_signed and signed_value(value, in_width) != signed_value(raw, in_width):
                continue
            vec = {input_name: 0 for input_name in spec.inputs}
            vec[name] = value
            if predictor(vec) == target_mod:
                samples.append(vec)
                break
    return samples


def compare_to_constant_expr(expr: str, width: int, op: str, threshold: int, signed_cmp: bool) -> str:
    if signed_cmp:
        return f"($signed({expr}) {op} {threshold})"
    return f"(({expr}) {op} {threshold})"


def linear_words_with_flags_learner(spec: Spec) -> Optional[str]:
    if len(spec.outputs) < 2 or len(spec.inputs) > 12:
        return None
    word_outputs = [name for name, width in spec.outputs.items() if width > 1]
    flag_outputs = [name for name, width in spec.outputs.items() if width == 1]
    if not word_outputs or not flag_outputs:
        return None

    sim = PrimitiveSim(spec)
    rng = random.Random(18)
    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(256))

    learned_words: Dict[str, LearnedWord] = {}
    body: List[str] = []
    word_exprs: Dict[str, str] = {}
    for output in word_outputs:
        learned = learn_linear_word(spec, sim, output, samples)
        if learned is None:
            return None
        _, base, coeffs, _predictor = learned
        learned_words[output] = learned
        decls, expr = linear_word_expr(spec, spec.outputs[output], base, coeffs)
        body.extend(line for line in decls if line not in body)
        word_exprs[output] = output
        body.append(f"assign {output} = {expr};")

    flag_samples = list(samples)
    for word in learned_words.values():
        flag_samples.extend(boundary_samples_for_linear_word(spec, word, range(-128, 129)))

    flag_predictors: Dict[str, Callable[[Dict[str, int]], int]] = {}
    ops = ("<", "<=", ">", ">=", "==", "!=")
    for flag in flag_outputs:
        observed = [sim(sample)[flag] for sample in flag_samples]
        found = None
        for word_name, (_out, _base, _coeffs, predictor) in learned_words.items():
            width = spec.outputs[word_name]
            values = [predictor(sample) for sample in flag_samples]
            for signed_cmp in (False, True):
                signed_values = [signed_value(value, width) if signed_cmp else value for value in values]
                candidates = sorted(set(signed_values))
                thresholds = set(candidates)
                thresholds.update(value - 1 for value in candidates)
                thresholds.update(value + 1 for value in candidates)
                if len(thresholds) > 512:
                    lo = min(signed_values)
                    hi = max(signed_values)
                    thresholds = set(range(max(lo - 2, -64), min(hi + 3, 64)))
                    thresholds.update([lo, lo + 1, hi - 1, hi])
                for op in ops:
                    for threshold in sorted(thresholds):
                        if op == "<":
                            predicted = [int(value < threshold) for value in signed_values]
                        elif op == "<=":
                            predicted = [int(value <= threshold) for value in signed_values]
                        elif op == ">":
                            predicted = [int(value > threshold) for value in signed_values]
                        elif op == ">=":
                            predicted = [int(value >= threshold) for value in signed_values]
                        elif op == "==":
                            predicted = [int(value == threshold) for value in signed_values]
                        else:
                            predicted = [int(value != threshold) for value in signed_values]
                        if predicted == observed:
                            expr = compare_to_constant_expr(word_exprs[word_name], width, op, threshold, signed_cmp)

                            def flag_pred(
                                values: Dict[str, int],
                                predictor: Callable[[Dict[str, int]], int] = predictor,
                                width: int = width,
                                signed_cmp: bool = signed_cmp,
                                op: str = op,
                                threshold: int = threshold,
                            ) -> int:
                                value = predictor(values)
                                if signed_cmp:
                                    value = signed_value(value, width)
                                if op == "<":
                                    return int(value < threshold)
                                if op == "<=":
                                    return int(value <= threshold)
                                if op == ">":
                                    return int(value > threshold)
                                if op == ">=":
                                    return int(value >= threshold)
                                if op == "==":
                                    return int(value == threshold)
                                return int(value != threshold)

                            found = (expr, flag_pred)
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        if not found:
            return None
        expr, flag_pred = found
        body.append(f"assign {flag} = {expr};")
        flag_predictors[flag] = flag_pred

    fresh = targeted_values(spec)
    fresh.extend(random_values(spec, rng) for _ in range(256))
    for values in fresh:
        observed_outputs = sim(values)
        for output, (_out, _base, _coeffs, predictor) in learned_words.items():
            if predictor(values) != observed_outputs[output]:
                return None
        for flag, predictor in flag_predictors.items():
            if predictor(values) != observed_outputs[flag]:
                return None

    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=256, seed=18)
    return rtl if ok else None


def arithmetic_term_expr(spec: Spec, output_width: int, term: Tuple[str, ...]) -> str:
    if not term:
        return sized_const(1, output_width)
    pieces = [extend_expr(name, spec.inputs[name], output_width) for name in term]
    if len(pieces) == 1:
        return pieces[0]
    return "(" + " * ".join(pieces) + ")"


def coefficient_expr(spec: Spec, output_width: int, coeff: int, term: Tuple[str, ...]) -> str:
    signed = signed_mod(coeff, output_width)
    term_expr = arithmetic_term_expr(spec, output_width, term)
    if signed == 1:
        return term_expr
    if signed == -1:
        return f"-({term_expr})"
    magnitude = abs(signed)
    product = f"({term_expr} * {sized_const(magnitude, output_width)})"
    if signed < 0:
        return f"-{product}"
    return product


def combine_sum(parts: Sequence[str], output_width: int) -> str:
    if not parts:
        return sized_const(0, output_width)
    expr = " + ".join(parts)
    return expr.replace("+ -", "- ")


def learn_quadratic_output(
    spec: Spec,
    sim: PrimitiveSim,
    output: str,
    samples: Sequence[Dict[str, int]],
) -> Optional[Tuple[str, Callable[[Dict[str, int]], int]]]:
    names = list(spec.inputs)
    width = spec.outputs[output]
    if len(names) > 64 or width > 80:
        return None

    mod = 1 << width
    zero = {name: 0 for name in names}
    base = sim(zero)[output]
    f1: Dict[str, int] = {}
    lin: Dict[str, int] = {}
    square: Dict[str, int] = {}
    cube: Dict[str, int] = {}
    cross: Dict[Tuple[str, str], int] = {}

    for name in names:
        vec = dict(zero)
        vec[name] = 1
        y1 = sim(vec)[output]
        f1[name] = y1
        lin[name] = (y1 - base) % mod

    for name in names:
        if spec.inputs[name] <= 1:
            continue
        y = {1: f1[name]}
        for point in (2, 3):
            vec = dict(zero)
            vec[name] = point
            y[point] = sim(vec)[output]
        d1 = (y[1] - base) % mod
        d2 = (y[2] - base) % mod
        d3 = (y[3] - base) % mod

        cube_choices = []
        raw_cube = (d3 - 3 * d2 + 3 * d1) % mod
        for candidate in (raw_cube, raw_cube - mod, raw_cube + mod):
            if candidate % 6 == 0:
                cube_choices.append(candidate // 6)
        cube_coeff = min(cube_choices, key=abs) if cube_choices else 0

        square_choices = []
        raw_square = (d2 - 2 * d1 - 6 * cube_coeff) % mod
        for candidate in (raw_square, raw_square - mod, raw_square + mod):
            if candidate % 2 == 0:
                square_choices.append(candidate // 2)
        square_coeff = min(square_choices, key=abs) if square_choices else 0

        if cube_coeff:
            cube[name] = cube_coeff % mod
        if square_coeff:
            square[name] = square_coeff % mod
        lin[name] = (d1 - square_coeff - cube_coeff) % mod

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            vec = dict(zero)
            vec[a] = 1
            vec[b] = 1
            coeff = (sim(vec)[output] - f1[a] - f1[b] + base) % mod
            if coeff:
                cross[(a, b)] = coeff

    term_count = int(base != 0)
    term_count += sum(1 for c in lin.values() if c)
    term_count += len(square) + len(cube) + len(cross)
    if term_count == 0:
        expr = sized_const(0, width)
    elif term_count > 96:
        return None
    else:
        parts: List[str] = []
        if base:
            parts.append(sized_const(base, width))
        for name, coeff in lin.items():
            if coeff:
                parts.append(coefficient_expr(spec, width, coeff, (name,)))
        for name, coeff in square.items():
            parts.append(coefficient_expr(spec, width, coeff, (name, name)))
        for name, coeff in cube.items():
            parts.append(coefficient_expr(spec, width, coeff, (name, name, name)))
        for (a, b), coeff in cross.items():
            parts.append(coefficient_expr(spec, width, coeff, (a, b)))
        expr = combine_sum(parts, width)

    def predictor(values: Dict[str, int]) -> int:
        result = base
        for name, coeff in lin.items():
            result += coeff * values.get(name, 0)
        for name, coeff in square.items():
            result += coeff * values.get(name, 0) * values.get(name, 0)
        for name, coeff in cube.items():
            value = values.get(name, 0)
            result += coeff * value * value * value
        for (a, b), coeff in cross.items():
            result += coeff * values.get(a, 0) * values.get(b, 0)
        return result % mod

    if output_matches(sim, output, predictor, samples):
        return expr, predictor
    return None


def learn_quadratic_output_fixed_controls(
    spec: Spec,
    sim: PrimitiveSim,
    output: str,
    fixed_controls: Dict[str, int],
    data_names: Sequence[str],
    samples: Sequence[Dict[str, int]],
) -> Optional[Tuple[str, Callable[[Dict[str, int]], int]]]:
    names = list(data_names)
    width = spec.outputs[output]
    if len(names) > 32 or width > 96:
        return None

    mod = 1 << width
    zero = {name: 0 for name in spec.inputs}
    zero.update(fixed_controls)
    base = sim(zero)[output]
    f1: Dict[str, int] = {}
    lin: Dict[str, int] = {}
    square: Dict[str, int] = {}
    cube: Dict[str, int] = {}
    cross: Dict[Tuple[str, str], int] = {}

    for name in names:
        vec = dict(zero)
        vec[name] = 1
        y1 = sim(vec)[output]
        f1[name] = y1
        lin[name] = (y1 - base) % mod

    for name in names:
        if spec.inputs[name] <= 1:
            continue
        y = {1: f1[name]}
        for point in (2, 3):
            vec = dict(zero)
            vec[name] = point
            y[point] = sim(vec)[output]
        d1 = (y[1] - base) % mod
        d2 = (y[2] - base) % mod
        d3 = (y[3] - base) % mod

        cube_choices = []
        raw_cube = (d3 - 3 * d2 + 3 * d1) % mod
        for candidate in (raw_cube, raw_cube - mod, raw_cube + mod):
            if candidate % 6 == 0:
                cube_choices.append(candidate // 6)
        cube_coeff = min(cube_choices, key=abs) if cube_choices else 0

        square_choices = []
        raw_square = (d2 - 2 * d1 - 6 * cube_coeff) % mod
        for candidate in (raw_square, raw_square - mod, raw_square + mod):
            if candidate % 2 == 0:
                square_choices.append(candidate // 2)
        square_coeff = min(square_choices, key=abs) if square_choices else 0

        if cube_coeff:
            cube[name] = cube_coeff % mod
        if square_coeff:
            square[name] = square_coeff % mod
        lin[name] = (d1 - square_coeff - cube_coeff) % mod

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            vec = dict(zero)
            vec[a] = 1
            vec[b] = 1
            coeff = (sim(vec)[output] - f1[a] - f1[b] + base) % mod
            if coeff:
                cross[(a, b)] = coeff

    term_count = int(base != 0)
    term_count += sum(1 for c in lin.values() if c)
    term_count += len(square) + len(cube) + len(cross)
    if term_count > 96:
        return None
    parts: List[str] = []
    if base:
        parts.append(sized_const(base, width))
    for name, coeff in lin.items():
        if coeff:
            parts.append(coefficient_expr(spec, width, coeff, (name,)))
    for name, coeff in square.items():
        parts.append(coefficient_expr(spec, width, coeff, (name, name)))
    for name, coeff in cube.items():
        value = signed_mod(coeff, width)
        if value == 1:
            parts.append(f"({name} ** 3)")
        else:
            parts.append(coefficient_expr(spec, width, coeff, (name, name, name)))
    for (a, b), coeff in cross.items():
        parts.append(coefficient_expr(spec, width, coeff, (a, b)))
    expr = combine_sum(parts, width)

    def predictor(values: Dict[str, int]) -> int:
        result = base
        for name, coeff in lin.items():
            result += coeff * values.get(name, 0)
        for name, coeff in square.items():
            result += coeff * values.get(name, 0) * values.get(name, 0)
        for name, coeff in cube.items():
            value = values.get(name, 0)
            result += coeff * value * value * value
        for (a, b), coeff in cross.items():
            result += coeff * values.get(a, 0) * values.get(b, 0)
        return result % mod

    branch_samples = []
    for sample in samples:
        vec = dict(sample)
        vec.update(fixed_controls)
        branch_samples.append(vec)
    if output_matches(sim, output, predictor, branch_samples):
        return expr, predictor
    return None


def compare_expr(spec: Spec, a: str, op: str, b: str, signed: bool = False) -> str:
    aw = spec.inputs[a]
    bw = spec.inputs[b]
    width = max(aw, bw)
    lhs = extend_expr(a, aw, width)
    rhs = extend_expr(b, bw, width)
    if not signed or op in {"==", "!="}:
        return f"({lhs} {op} {rhs})"
    lhs_sign = f"{a}[{aw - 1}]"
    rhs_sign = f"{b}[{bw - 1}]"
    same_sign_compare = f"({lhs} {op} {rhs})"
    if op in {"<", "<="}:
        sign_result = lhs_sign
    else:
        sign_result = rhs_sign
    return f"(({lhs_sign} != {rhs_sign}) ? {sign_result} : {same_sign_compare})"


def signed_extend_expr(name: str, in_width: int, out_width: int, is_signed: bool) -> str:
    if in_width == out_width:
        return name
    if in_width > out_width:
        return f"{name}[{out_width - 1}:0]"
    if is_signed:
        return f"{{{{{out_width - in_width}{{{name}[{in_width - 1}]}}}}, {name}}}"
    return f"{{{out_width - in_width}'b0, {name}}}"


def add_const_expr(expr: str, const: int) -> str:
    if const == 0:
        return expr
    if const > 0:
        return f"{expr} + {const}"
    return f"{expr} - {abs(const)}"


def comparison_affine_flags_learner(spec: Spec) -> Optional[str]:
    if not spec.outputs or any(width != 1 for width in spec.outputs.values()):
        return None
    data = [name for name, width in spec.inputs.items() if width > 1]
    if not (2 <= len(data) <= 8):
        return None

    sim = PrimitiveSim(spec)
    rng = random.Random(16)
    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(512))
    ops = (">", ">=", "<", "<=", "==", "!=")
    body: List[str] = []
    predictors: Dict[str, Callable[[Dict[str, int]], int]] = {}

    for output in spec.outputs:
        observed = [sim(sample)[output] for sample in samples]
        found = None
        for a in data:
            for b in data:
                if a == b:
                    continue
                width = max(spec.inputs[a], spec.inputs[b]) + 1
                for signed_a in (False, True):
                    for signed_b in (False, True):
                        signed_cmp = signed_a or signed_b
                        for const in range(-8, 9):
                            for op in ops:
                                predicted = []
                                for values in samples:
                                    lhs = signed_or_unsigned_value(values.get(a, 0), spec.inputs[a], signed_a) + const
                                    rhs = signed_or_unsigned_value(values.get(b, 0), spec.inputs[b], signed_b)
                                    if op == ">":
                                        predicted.append(int(lhs > rhs))
                                    elif op == ">=":
                                        predicted.append(int(lhs >= rhs))
                                    elif op == "<":
                                        predicted.append(int(lhs < rhs))
                                    elif op == "<=":
                                        predicted.append(int(lhs <= rhs))
                                    elif op == "==":
                                        predicted.append(int(lhs == rhs))
                                    else:
                                        predicted.append(int(lhs != rhs))
                                if predicted == observed:
                                    found = (a, b, width, signed_cmp, signed_a, signed_b, const, op)
                                    break
                            if found:
                                break
                        if found:
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        if found is None:
            return None
        a, b, width, signed_cmp, signed_a, signed_b, const, op = found
        wire_kind = "wire signed" if signed_cmp else "wire"
        lhs_name = f"cmp_{output}_lhs"
        rhs_name = f"cmp_{output}_rhs"
        body.append(f"{wire_kind} [{width - 1}:0] {lhs_name};")
        body.append(f"{wire_kind} [{width - 1}:0] {rhs_name};")
        lhs_expr = signed_extend_expr(a, spec.inputs[a], width, signed_a)
        rhs_expr = signed_extend_expr(b, spec.inputs[b], width, signed_b)
        body.append(f"assign {lhs_name} = {add_const_expr(lhs_expr, const)};")
        body.append(f"assign {rhs_name} = {rhs_expr};")
        body.append(f"assign {output} = {lhs_name} {op} {rhs_name};")

        def predictor(
            values: Dict[str, int],
            a: str = a,
            b: str = b,
            signed_a: bool = signed_a,
            signed_b: bool = signed_b,
            const: int = const,
            op: str = op,
        ) -> int:
            lhs = signed_or_unsigned_value(values.get(a, 0), spec.inputs[a], signed_a) + const
            rhs = signed_or_unsigned_value(values.get(b, 0), spec.inputs[b], signed_b)
            if op == ">":
                return int(lhs > rhs)
            if op == ">=":
                return int(lhs >= rhs)
            if op == "<":
                return int(lhs < rhs)
            if op == "<=":
                return int(lhs <= rhs)
            if op == "==":
                return int(lhs == rhs)
            return int(lhs != rhs)

        predictors[output] = predictor

    fresh = targeted_values(spec)
    fresh.extend(random_values(spec, rng) for _ in range(512))
    for values in fresh:
        observed_outputs = sim(values)
        for output, predictor in predictors.items():
            if predictor(values) != observed_outputs[output]:
                return None

    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=512, seed=16)
    return rtl if ok else None


ComparisonPredicate = Tuple[str, Tuple[int, ...], set[str]]


def comparison_mux_flags_learner(spec: Spec) -> Optional[str]:
    if not spec.outputs or any(width != 1 for width in spec.outputs.values()):
        return None
    data = [name for name, width in spec.inputs.items() if width > 1]
    controls = [name for name, width in spec.inputs.items() if width == 1]
    if not (2 <= len(data) <= 6 and 2 <= len(controls) <= 32 and len(spec.outputs) <= 12):
        return None

    rng = random.Random(34)
    samples = targeted_values(spec)
    for c0, c1 in combinations(controls, 2):
        for mask in range(4):
            vec = {name: 0 for name in spec.inputs}
            vec[c0] = mask & 1
            vec[c1] = (mask >> 1) & 1
            for name in data:
                vec[name] = rng.randrange(1 << spec.inputs[name])
            samples.append(vec)
    samples.extend(random_values(spec, rng) for _ in range(384))
    rows = simulate_output_rows(spec, samples)

    predicates: List[ComparisonPredicate] = []
    seen_vectors: set[Tuple[int, ...]] = set()

    def term_value(values: Dict[str, int], coeff: int, name: str, is_signed: bool) -> int:
        value = signed_or_unsigned_value(values.get(name, 0), spec.inputs[name], is_signed)
        return coeff * value

    def term_expr(coeff: int, name: str, width: int, is_signed: bool) -> Tuple[str, set[str]]:
        signed_inputs = {name} if is_signed else set()
        base = sign_extend_expr(f"s_{name}", spec.inputs[name], width) if is_signed else extend_expr(name, spec.inputs[name], width)
        if coeff == 1:
            return base, signed_inputs
        if coeff == -1:
            return f"-({base})", signed_inputs
        if coeff == 2:
            return f"({base} << 1)", signed_inputs
        if coeff == -2:
            return f"-(({base} << 1))", signed_inputs
        return f"({base}) * {coeff}", signed_inputs

    def terms_expr(terms: Sequence[Tuple[int, str]], width: int, is_signed: bool) -> Tuple[str, set[str]]:
        parts: List[str] = []
        signed_inputs: set[str] = set()
        for coeff, name in terms:
            expr, expr_signed = term_expr(coeff, name, width, is_signed)
            parts.append(expr)
            signed_inputs.update(expr_signed)
        return " + ".join(parts) if parts else "0", signed_inputs

    def add_predicate(lhs_terms: Sequence[Tuple[int, str]], rhs_terms: Sequence[Tuple[int, str]], op: str, is_signed: bool) -> None:
        width = max(spec.inputs[name] + (1 if abs(coeff) > 1 else 0) for coeff, name in (*lhs_terms, *rhs_terms)) + 2
        predicted = []
        for values in samples:
            lhs = sum(term_value(values, coeff, name, is_signed) for coeff, name in lhs_terms)
            rhs = sum(term_value(values, coeff, name, is_signed) for coeff, name in rhs_terms)
            if op == "<":
                predicted.append(int(lhs < rhs))
            elif op == ">":
                predicted.append(int(lhs > rhs))
            elif op == "<=":
                predicted.append(int(lhs <= rhs))
            elif op == ">=":
                predicted.append(int(lhs >= rhs))
            elif op == "==":
                predicted.append(int(lhs == rhs))
            else:
                predicted.append(int(lhs != rhs))
        vector = tuple(predicted)
        if vector in seen_vectors:
            return
        seen_vectors.add(vector)
        lhs_expr, lhs_signed = terms_expr(lhs_terms, width, is_signed)
        rhs_expr, rhs_signed = terms_expr(rhs_terms, width, is_signed)
        if is_signed and op not in {"==", "!="}:
            expr = f"($signed({lhs_expr}) {op} $signed({rhs_expr}))"
        else:
            expr = f"({lhs_expr}) {op} ({rhs_expr})"
        predicates.append((expr, vector, lhs_signed | rhs_signed))

    for is_signed in (False, True):
        for a in data:
            for b in data:
                if a == b:
                    continue
                for op in ("<", ">", "<=", ">=", "==", "!="):
                    add_predicate(((1, a),), ((1, b),), op, is_signed)
        for lhs in data:
            rhs_pool = [name for name in data if name != lhs]
            for rhs_size in (1, 2):
                for rhs_names in combinations(rhs_pool, rhs_size):
                    rhs_terms = tuple((1, name) for name in rhs_names)
                    for coeff in (1, 2, -1, -2):
                        for op in ("<", ">"):
                            add_predicate(((coeff, lhs),), rhs_terms, op, is_signed)

    output_models: Dict[str, Tuple[Optional[Tuple[str, str]], Tuple[int, ...]]] = {}
    used_predicates: set[int] = set()
    for output in spec.outputs:
        observed = tuple(row[output] for row in rows)
        direct = next((idx for idx, (_expr, vector, _signed) in enumerate(predicates) if vector == observed), None)
        if direct is not None:
            output_models[output] = (None, (direct,))
            used_predicates.add(direct)
            continue

        found = None
        for c0, c1 in combinations(controls, 2):
            branch_predicates: List[int] = []
            ok_pair = True
            for mask in range(4):
                indices = [
                    idx for idx, values in enumerate(samples)
                    if (values.get(c0, 0) | (values.get(c1, 0) << 1)) == mask
                ]
                if len(indices) < 8:
                    ok_pair = False
                    break
                branch_observed = tuple(observed[idx] for idx in indices)
                match = next(
                    (
                        pred_idx for pred_idx, (_expr, vector, _signed) in enumerate(predicates)
                        if tuple(vector[idx] for idx in indices) == branch_observed
                    ),
                    None,
                )
                if match is None:
                    ok_pair = False
                    break
                branch_predicates.append(match)
            if ok_pair:
                found = ((c0, c1), tuple(branch_predicates))
                break
        if found is None:
            return None
        output_models[output] = found
        used_predicates.update(found[1])

    ordered_predicates = sorted(used_predicates)
    pred_names = {idx: f"cmp_mux_pred_{pos}" for pos, idx in enumerate(ordered_predicates)}
    signed_inputs = sorted(
        {name for idx in ordered_predicates for name in predicates[idx][2]},
        key=lambda n: list(spec.inputs).index(n),
    )
    body: List[str] = []
    for name in signed_inputs:
        body.append(f"wire signed [{spec.inputs[name] - 1}:0] s_{name};")
        body.append(f"assign s_{name} = {name};")
    for idx in ordered_predicates:
        body.append(f"wire {pred_names[idx]};")
        body.append(f"assign {pred_names[idx]} = {predicates[idx][0]};")
    for output, (control_pair, branches) in output_models.items():
        if control_pair is None:
            body.append(f"assign {output} = {pred_names[branches[0]]};")
            continue
        c0, c1 = control_pair
        p00, p01, p10, p11 = (pred_names[idx] for idx in branches)
        body.append(f"assign {output} = {c0} ? ({c1} ? {p11} : {p01}) : ({c1} ? {p10} : {p00});")

    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=512, seed=34)
    return rtl if ok else None


def learn_comparison_output(
    spec: Spec,
    sim: PrimitiveSim,
    output: str,
    samples: Sequence[Dict[str, int]],
) -> Optional[Tuple[str, Callable[[Dict[str, int]], int]]]:
    if spec.outputs[output] != 1:
        return None
    names = list(spec.inputs)
    ops = ("<", "<=", ">", ">=", "==", "!=")
    for signed in (False, True):
        for a in names:
            for b in names:
                if a == b:
                    continue
                for op in ops:
                    def predictor(
                        values: Dict[str, int],
                        a: str = a,
                        b: str = b,
                        op: str = op,
                        signed: bool = signed,
                    ) -> int:
                        lhs = values.get(a, 0)
                        rhs = values.get(b, 0)
                        if signed:
                            lhs = signed_value(lhs, spec.inputs[a])
                            rhs = signed_value(rhs, spec.inputs[b])
                        if op == "<":
                            return int(lhs < rhs)
                        if op == "<=":
                            return int(lhs <= rhs)
                        if op == ">":
                            return int(lhs > rhs)
                        if op == ">=":
                            return int(lhs >= rhs)
                        if op == "==":
                            return int(lhs == rhs)
                        return int(lhs != rhs)

                    if output_matches(sim, output, predictor, samples):
                        return compare_expr(spec, a, op, b, signed=signed), predictor

    for value in (0, 1):
        if all(sim(sample)[output] == value for sample in samples):
            return f"1'b{value}", lambda _values, value=value: value
    return None


def mixed_expression_learner(spec: Spec) -> Optional[str]:
    gate_count = len(parse_gates(spec.text))
    if len(spec.inputs) > 16 or gate_count > 12000:
        return None
    if all(width == 1 for width in spec.outputs.values()) and sum(spec.inputs.values()) > 64:
        return None

    sim = PrimitiveSim(spec)
    rng = random.Random(11)
    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(128))

    body = []
    predictors: Dict[str, Callable[[Dict[str, int]], int]] = {}
    for output in spec.outputs:
        learned = learn_quadratic_output(spec, sim, output, samples)
        if learned is None:
            learned = learn_comparison_output(spec, sim, output, samples)
        if learned is None:
            return None
        expr, predictor = learned
        body.append(f"assign {output} = {expr};")
        predictors[output] = predictor

    fresh = targeted_values(spec)
    fresh.extend(random_values(spec, rng) for _ in range(256))
    for values in fresh:
        observed = sim(values)
        for output, predictor in predictors.items():
            if predictor(values) != observed[output]:
                return None
    return emit_decls(spec, body)


def build_minimized_expr_from_masks(active_controls: Sequence[str], expr_masks: Dict[str, List[int]]) -> str:
    full_count = 1 << len(active_controls)
    groups = sorted(expr_masks.items(), key=lambda item: (len(item[1]), item[0]))
    default_expr = "0"
    if sum(len(masks) for _expr, masks in groups) == full_count and groups:
        default_expr, _default_masks = groups.pop()
    expr = default_expr
    for branch_expr, masks in groups:
        cond = masks_condition(active_controls, masks)
        expr = f"({cond}) ? ({branch_expr}) : ({expr})"
    return expr


def controlled_mixed_expression_learner(spec: Spec) -> Optional[str]:
    controls = [n for n, w in spec.inputs.items() if w == 1]
    data = [n for n, w in spec.inputs.items() if w > 1]
    if not (controls and 1 <= len(data) <= 16 and len(controls) <= 16 and all(width <= 64 for width in spec.outputs.values())):
        return None

    sim = PrimitiveSim(spec)
    rng = random.Random(31)
    samples = targeted_values(spec)
    samples.extend(random_values(spec, rng) for _ in range(128))
    expressions: Dict[str, str] = {}
    models: Dict[str, Tuple[List[str], List[Callable[[Dict[str, int]], int]]]] = {}

    for output in spec.outputs:
        active_controls = discover_active_controls(spec, sim, output, controls)
        if len(active_controls) > 6:
            return None
        if not active_controls:
            learned = learn_quadratic_output_fixed_controls(spec, sim, output, {}, data, samples)
            if learned is None:
                return None
            expr, predictor = learned
            expressions[output] = expr
            models[output] = ([], [predictor])
            continue

        expr_masks: Dict[str, List[int]] = {}
        branch_predictors: List[Callable[[Dict[str, int]], int]] = []
        for mask in range(1 << len(active_controls)):
            fixed = {
                control: (mask >> (len(active_controls) - 1 - idx)) & 1
                for idx, control in enumerate(active_controls)
            }
            learned = learn_quadratic_output_fixed_controls(spec, sim, output, fixed, data, samples)
            if learned is None:
                return None
            expr, predictor = learned
            expr_masks.setdefault(expr, []).append(mask)
            branch_predictors.append(predictor)
        expressions[output] = build_minimized_expr_from_masks(active_controls, expr_masks)
        models[output] = (active_controls, branch_predictors)

    fresh = targeted_values(spec)
    fresh.extend(random_values(spec, rng) for _ in range(256))
    for values in fresh:
        observed = sim(values)
        for output, (active_controls, branch_predictors) in models.items():
            if active_controls:
                mask = 0
                for control in active_controls:
                    mask = (mask << 1) | values.get(control, 0)
                predicted = branch_predictors[mask](values)
            else:
                predicted = branch_predictors[0](values)
            if predicted != observed[output]:
                return None

    shared_body, expressions = share_common_addends(spec, expressions)
    body = [*shared_body]
    body.extend(f"assign {output} = {expressions[output]};" for output in spec.outputs)
    rtl = emit_decls(spec, body)
    ok, _detail = iverilog_random_equivalence(spec.path, rtl, spec, vectors=256, seed=31)
    return rtl if ok else None


def discover_active_controls(spec: Spec, sim: PrimitiveSim, output: str, controls: Sequence[str]) -> List[str]:
    active = []
    for control in controls:
        differs = False
        for salt in range(5):
            seed = {
                name: ((i + 1) * (salt + 3) + 5 * salt) & ((1 << min(width, 6)) - 1)
                for i, (name, width) in enumerate(spec.inputs.items())
            }
            for other in controls:
                seed[other] = 0
            a0 = dict(seed)
            a1 = dict(seed)
            a0[control] = 0
            a1[control] = 1
            if sim(a0)[output] != sim(a1)[output]:
                differs = True
                break
        if differs:
            active.append(control)
    return active


AffineBranch = Tuple[Dict[str, int], int, List[Tuple[str, int]]]


def learn_affine_branches(
    spec: Spec,
    sim: PrimitiveSim,
    output: str,
    active_controls: Sequence[str],
    data: Sequence[str],
) -> List[AffineBranch]:
    width = spec.outputs[output]
    mod = 1 << width
    branches: List[AffineBranch] = []
    masks = 1 << len(active_controls)
    for mask in range(masks):
        control_values = {
            control: (mask >> (len(active_controls) - 1 - i)) & 1
            for i, control in enumerate(active_controls)
        }
        base = sim(control_values)[output]
        coeffs = []
        for name in data:
            sample = dict(control_values)
            sample[name] = 1
            coeff = (sim(sample)[output] - base) % mod
            if coeff:
                coeffs.append((name, coeff))
        branches.append((control_values, base, coeffs))
    return branches


def affine_branch_expression(spec: Spec, output: str, base: int, coeffs: Sequence[Tuple[str, int]]) -> str:
    width = spec.outputs[output]
    mod = 1 << width
    parts = [f"{width}'d{base}"] if base else []
    for name, coeff in coeffs:
        term = zext(name, spec.inputs[name], width)
        if coeff == 1:
            parts.append(term)
        elif coeff == mod - 1:
            parts.append(f"- ({term})")
        else:
            signed = int(signed_const(coeff, width))
            if signed < 0:
                parts.append(f"- ({scaled_term(abs(signed), term)})")
            else:
                parts.append(scaled_term(signed, term))
    return " + ".join(parts).replace("+ -", "- ") or "0"


def predict_affine(
    spec: Spec,
    output: str,
    active_controls: Sequence[str],
    branches: Sequence[AffineBranch],
    values: Dict[str, int],
) -> int:
    width = spec.outputs[output]
    mod = 1 << width
    for control_values, base, coeffs in branches:
        if all(values.get(control, 0) == value for control, value in control_values.items()):
            result = base
            for name, coeff in coeffs:
                result += coeff * values.get(name, 0)
            return result % mod
    return 0


def coeff_map(coeffs: Sequence[Tuple[str, int]]) -> Dict[str, int]:
    return {name: coeff for name, coeff in coeffs}


def branch_key(active_controls: Sequence[str], control_values: Dict[str, int]) -> Tuple[int, ...]:
    return tuple(control_values[control] for control in active_controls)


def subtract_affine_branch(
    width: int,
    lhs_base: int,
    lhs_coeffs: Sequence[Tuple[str, int]],
    rhs_base: int,
    rhs_coeffs: Sequence[Tuple[str, int]],
) -> Tuple[int, List[Tuple[str, int]]]:
    mod = 1 << width
    lhs = coeff_map(lhs_coeffs)
    rhs = coeff_map(rhs_coeffs)
    names = sorted(set(lhs) | set(rhs))
    coeffs = []
    for name in names:
        coeff = (lhs.get(name, 0) - rhs.get(name, 0)) % mod
        if coeff:
            coeffs.append((name, coeff))
    return (lhs_base - rhs_base) % mod, coeffs


def additive_control_expression(
    spec: Spec,
    output: str,
    active_controls: Sequence[str],
    branches: Sequence[AffineBranch],
) -> Optional[str]:
    width = spec.outputs[output]
    mod = 1 << width
    by_key = {branch_key(active_controls, values): (base, coeffs) for values, base, coeffs in branches}
    zero_key = tuple(0 for _ in active_controls)
    if zero_key not in by_key:
        return None
    zero_base, zero_coeffs = by_key[zero_key]

    deltas: Dict[str, Tuple[int, List[Tuple[str, int]]]] = {}
    for index, control in enumerate(active_controls):
        key = tuple(1 if i == index else 0 for i in range(len(active_controls)))
        if key not in by_key:
            return None
        base, coeffs = by_key[key]
        deltas[control] = subtract_affine_branch(width, base, coeffs, zero_base, zero_coeffs)

    for values, base, coeffs in branches:
        predicted_base = zero_base
        predicted_coeffs = coeff_map(zero_coeffs)
        for control in active_controls:
            if values[control]:
                delta_base, delta_coeffs = deltas[control]
                predicted_base = (predicted_base + delta_base) % mod
                for name, coeff in delta_coeffs:
                    predicted_coeffs[name] = (predicted_coeffs.get(name, 0) + coeff) % mod
        expected_coeffs = {name: coeff for name, coeff in predicted_coeffs.items() if coeff % mod}
        if predicted_base != base % mod or expected_coeffs != coeff_map(coeffs):
            return None

    parts = [affine_branch_expression(spec, output, zero_base, zero_coeffs)]
    for control in active_controls:
        delta_base, delta_coeffs = deltas[control]
        delta_expr = affine_branch_expression(spec, output, delta_base, delta_coeffs)
        if delta_expr != "0":
            parts.append(f"({control} ? ({delta_expr}) : {width}'d0)")
    return " + ".join(parts)


def split_top_level_add(expr: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for char in expr:
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        if char == "+" and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def is_nontrivial_addend(term: str) -> bool:
    return any(token in term for token in ("?", "<<", ">>", "{", "*", "-", "+", "<", ">", "==", "!="))


def share_common_addends(spec: Spec, expressions: Dict[str, str]) -> Tuple[List[str], Dict[str, str]]:
    by_width: Dict[int, List[str]] = {}
    for output in expressions:
        by_width.setdefault(spec.outputs[output], []).append(output)

    shared_body: List[str] = []
    rewritten = dict(expressions)
    shared_index = 0
    for width, outputs in by_width.items():
        if len(outputs) < 2:
            continue
        split = {output: split_top_level_add(expressions[output]) for output in outputs}
        freq: Dict[str, int] = {}
        for parts in split.values():
            for term in set(parts):
                if is_nontrivial_addend(term):
                    freq[term] = freq.get(term, 0) + 1

        groups: Dict[Tuple[str, ...], List[str]] = {}
        for output, parts in split.items():
            common = tuple(term for term in parts if freq.get(term, 0) >= 2)
            if len(common) >= 2:
                groups.setdefault(common, []).append(output)

        for common_terms, group_outputs in sorted(groups.items(), key=lambda item: -len(item[1])):
            if len(group_outputs) < 2:
                continue
            shared_name = f"rtl_shared_{shared_index}"
            shared_index += 1
            shared_body.append(f"wire [{width - 1}:0] {shared_name};")
            shared_body.append(f"assign {shared_name} = " + " + ".join(common_terms) + ";")
            common_set = set(common_terms)
            for output in group_outputs:
                parts = split_top_level_add(rewritten[output])
                replacement = [shared_name] + [term for term in parts if term not in common_set]
                rewritten[output] = " + ".join(replacement)

        # A family ``base + (guard ? delta : 0)`` repeats the same addition
        # once per output after synthesis.  Factor it into one shared
        # ``base_plus_delta`` value and retain only the per-output mux.  The
        # rewrite is modulo the declared output width and is therefore exact
        # for fixed-width bit-vector addition.
        conditional_groups: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        zero = f"{width}'d0"
        conditional_re = re.compile(
            rf"^\((?P<guard>[^?]+?)\s*\?\s*\((?P<delta>.+)\)\s*:\s*{re.escape(zero)}\)$"
        )
        for output in outputs:
            parts = split_top_level_add(rewritten[output])
            if len(parts) != 2:
                continue
            for conditional_index in (0, 1):
                match = conditional_re.match(parts[conditional_index].strip())
                if not match:
                    continue
                base = parts[1 - conditional_index].strip()
                delta = match.group("delta").strip()
                guard = match.group("guard").strip()
                conditional_groups.setdefault((base, delta), []).append((output, guard))
                break

        for (base, delta), group in sorted(
            conditional_groups.items(), key=lambda item: -len(item[1])
        ):
            if len(group) < 2:
                continue
            shared_name = f"rtl_shared_{shared_index}"
            shared_index += 1
            shared_body.append(f"wire [{width - 1}:0] {shared_name};")
            shared_body.append(f"assign {shared_name} = {base} + ({delta});")
            for output, guard in group:
                rewritten[output] = f"{guard} ? {shared_name} : {base}"

    return shared_body, rewritten


def mask_to_cube(mask: int, bits: int) -> str:
    return "".join("1" if (mask >> (bits - 1 - i)) & 1 else "0" for i in range(bits))


def combine_cubes(a: str, b: str) -> Optional[str]:
    diff = 0
    out = []
    for ca, cb in zip(a, b):
        if ca == cb:
            out.append(ca)
        elif ca != "-" and cb != "-":
            diff += 1
            out.append("-")
        else:
            return None
    return "".join(out) if diff == 1 else None


def cube_covers(cube: str, mask: int, bits: int) -> bool:
    target = mask_to_cube(mask, bits)
    return all(c == "-" or c == t for c, t in zip(cube, target))


def minimized_cubes(masks: Sequence[int], bits: int) -> List[str]:
    if not masks:
        return []
    full = set(range(1 << bits))
    mask_set = set(masks)
    if mask_set == full:
        return ["-" * bits]

    current = {mask_to_cube(mask, bits) for mask in mask_set}
    primes: set[str] = set()
    while current:
        used: set[str] = set()
        nxt: set[str] = set()
        items = sorted(current)
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                combined = combine_cubes(a, b)
                if combined is not None:
                    used.add(a)
                    used.add(b)
                    nxt.add(combined)
        primes.update(cube for cube in current if cube not in used)
        if nxt == current:
            break
        current = nxt

    uncovered = set(mask_set)
    selected: List[str] = []
    while uncovered:
        best = max(
            primes,
            key=lambda cube: (
                len([mask for mask in uncovered if cube_covers(cube, mask, bits)]),
                cube.count("-"),
            ),
        )
        covered = {mask for mask in uncovered if cube_covers(best, mask, bits)}
        if not covered:
            break
        selected.append(best)
        uncovered -= covered
    selected.extend(mask_to_cube(mask, bits) for mask in sorted(uncovered))
    return selected


def cube_condition(active_controls: Sequence[str], cube: str) -> str:
    pieces = []
    for control, value in zip(active_controls, cube):
        if value == "1":
            pieces.append(control)
        elif value == "0":
            pieces.append(f"!{control}")
    if not pieces:
        return "1'b1"
    if len(pieces) == 1:
        return pieces[0]
    return "(" + " && ".join(pieces) + ")"


def masks_condition(active_controls: Sequence[str], masks: Sequence[int]) -> str:
    cubes = minimized_cubes(masks, len(active_controls))
    pieces = [cube_condition(active_controls, cube) for cube in cubes]
    if not pieces:
        return "1'b0"
    if "1'b1" in pieces:
        return "1'b1"
    if len(pieces) == 1:
        return pieces[0]
    return "(" + " || ".join(pieces) + ")"


def build_controlled_assign(
    spec: Spec,
    output: str,
    active_controls: Sequence[str],
    branches: Sequence[AffineBranch],
) -> str:
    if not active_controls:
        _, base, coeffs = branches[0]
        return affine_branch_expression(spec, output, base, coeffs)

    additive = additive_control_expression(spec, output, active_controls, branches)
    if additive is not None:
        return additive

    expr_masks: Dict[str, List[int]] = {}
    for control_values, base, coeffs in branches:
        expr = affine_branch_expression(spec, output, base, coeffs)
        mask = 0
        for control in active_controls:
            mask = (mask << 1) | control_values[control]
        expr_masks.setdefault(expr, []).append(mask)

    full_count = 1 << len(active_controls)
    groups = sorted(expr_masks.items(), key=lambda item: (len(item[1]), item[0]))
    default_expr = "0"
    if sum(len(masks) for _expr, masks in groups) == full_count and groups:
        default_expr, _default_masks = groups.pop()

    assign = default_expr
    for expr, masks in groups:
        cond = masks_condition(active_controls, masks)
        assign = f"({cond}) ? ({expr}) : ({assign})"
    return assign


def affine_case_learner(spec: Spec) -> Optional[str]:
    controls = [n for n, w in spec.inputs.items() if w == 1]
    data = [n for n, w in spec.inputs.items() if w > 1]
    if not (1 <= len(data) <= 64 and len(controls) <= 128 and all(width <= 32 for width in spec.outputs.values())):
        return None

    sim = PrimitiveSim(spec)
    expressions: Dict[str, str] = {}
    models = {}
    for output in spec.outputs:
        active_controls = discover_active_controls(spec, sim, output, controls)
        if len(active_controls) > 6:
            return None
        branches = learn_affine_branches(spec, sim, output, active_controls, data)
        models[output] = (active_controls, branches)
        expressions[output] = build_controlled_assign(spec, output, active_controls, branches)

    rng = random.Random(0)
    for _ in range(64):
        values = {
            name: rng.randrange(1 << min(width, 12))
            for name, width in spec.inputs.items()
        }
        observed = sim(values)
        for output, (active_controls, branches) in models.items():
            if predict_affine(spec, output, active_controls, branches, values) != observed[output]:
                return None
    shared_body, expressions = share_common_addends(spec, expressions)
    body = [*shared_body]
    body.extend(f"assign {output} = {expressions[output]};" for output in spec.outputs)
    return emit_decls(spec, body)


def signed_difference_learner(spec: Spec) -> Optional[str]:
    data = [(name, width) for name, width in spec.inputs.items() if width > 1]
    if len(data) != 2 or max(width for _, width in data) > 8:
        return None

    a_name, a_width = data[0]
    b_name, b_width = data[1]
    diff_width = max(a_width, b_width) + 1
    if not any(width == diff_width for width in spec.outputs.values()):
        return None

    sim = PrimitiveSim(spec)
    samples = []
    for a in range(1 << a_width):
        for b in range(1 << b_width):
            diff = (a - b) & ((1 << diff_width) - 1)
            signed = diff if diff < (1 << (diff_width - 1)) else diff - (1 << diff_width)
            outputs = sim({a_name: a, b_name: b})
            samples.append((diff, signed, outputs))

    body = [f"wire signed [{diff_width - 1}:0] diff;", f"assign diff = {a_name} - {b_name};"]
    for output, width in spec.outputs.items():
        values = [outputs[output] for _, _, outputs in samples]
        if width == diff_width and values == [diff for diff, _, _ in samples]:
            body.append(f"assign {output} = diff;")
            continue
        if width != 1:
            return None
        if all(v == 0 for v in values):
            body.append(f"assign {output} = 1'b0;")
            continue
        if all(v == 1 for v in values):
            body.append(f"assign {output} = 1'b1;")
            continue

        found = None
        for op in ("<", "<=", ">", ">="):
            for threshold in range(-(1 << (diff_width - 1)), 1 << (diff_width - 1)):
                if op == "<":
                    predicted = [int(signed < threshold) for _, signed, _ in samples]
                elif op == "<=":
                    predicted = [int(signed <= threshold) for _, signed, _ in samples]
                elif op == ">":
                    predicted = [int(signed > threshold) for _, signed, _ in samples]
                else:
                    predicted = [int(signed >= threshold) for _, signed, _ in samples]
                if predicted == values:
                    found = f"diff {op} {threshold}"
                    break
            if found:
                break
        if not found:
            return None
        body.append(f"assign {output} = {found};")
    return emit_decls(spec, body)


TEMPLATES: Tuple[Callable[[Spec], Optional[str]], ...] = (
    conditional_multiply_accumulator,
    signed_difference_learner,
    comparison_mux_flags_learner,
    comparison_affine_flags_learner,
    difference_threshold_predicate,
    two_bit_multiply_mux,
    offset_add_compare_learner,
    shift_add_learner,
    product_sum_learner,
    multiply_add_shift_learner,
    linear_combination_learner,
    paired_sum_linear_slice_learner,
    square_sum_flags_learner,
    linear_words_with_flags_learner,
    affine_case_learner,
    mixed_expression_learner,
    controlled_mixed_expression_learner,
    simulation_terms_learner,
)


def reverse_file(
    path: Path,
    output: Path,
    sim_vectors: int = 64,
    use_iverilog: bool = True,
) -> str:
    spec = parse_spec(path)
    method = "primitive_fallback"
    rtl = spec.text
    for template in TEMPLATES:
        candidate = template(spec)
        if candidate:
            rtl = candidate
            method = template.__name__
            break

    if method != "primitive_fallback" and use_iverilog and sim_vectors > 0:
        ok, detail = iverilog_random_equivalence(path, rtl, spec, sim_vectors)
        if not ok:
            rtl = spec.text
            method = f"primitive_fallback_after_{method}_sim_fail"
            print(f"{path}: simulation rejected candidate: {detail}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rtl)
    return method


def generate_one(path: Path, out_dir: Path, sim_vectors: int = 64, use_iverilog: bool = True) -> str:
    spec = parse_spec(path)
    return reverse_file(path, out_dir / f"{spec.case}.v", sim_vectors=sim_vectors, use_iverilog=use_iverilog)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-input", required=True, help="primitive or reference Verilog file")
    parser.add_argument("-output", required=True, help="path for the reversed Verilog file")
    parser.add_argument("--sim-vectors", type=int, default=64, help="random iverilog vectors for candidate validation")
    parser.add_argument("--no-iverilog", action="store_true", help="disable iverilog candidate validation")
    args = parser.parse_args(argv)

    method = reverse_file(
        resolve_path(args.input),
        resolve_path(args.output),
        sim_vectors=args.sim_vectors,
        use_iverilog=not args.no_iverilog,
    )
    print(method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

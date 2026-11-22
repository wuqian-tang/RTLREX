"""Complete-domain controls for compact structural Boolean emitters."""
from __future__ import annotations
import itertools
import random
import re
import tempfile
import unittest
from pathlib import Path

from truth.boolean_compact import emit_compact_robdd, emit_plain_robdd, emit_factored_anf, choose_compact_boolean
from truth.boolean_permutation import (find_output_permutations, emit_reusable_function,
                                       permutation_argument, reusable_function_within_budget)
from verify.truth_yosys import verify, default_yosys
from truth.boolean_fallback import choose_exact_boolean_fallback, emit_shared_anf, emit_shared_robdd
from cost.RTL_cost_calculator import evaluate_rtl


def replay_scalar(source, n_inputs, n_outputs):
    """Strict, independent complete-domain scalar Verilog evaluation.

    Consume the entire module/body/expression grammar, require exact ports,
    one driver per signal/output, declared dependencies and an acyclic DAG.
    """
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    source = re.sub(r'//[^\n]*', '', source)
    header = re.fullmatch(
        r'\s*module\s+top\s*\(\s*input\s*\[([0-9]+):0\]\s+x\s*,\s*'
        r'output\s*\[([0-9]+):0\]\s+y\s*\)\s*;(.*?)\bendmodule\s*',
        source, re.S)
    if not header or tuple(map(int, header.group(1, 2))) != (n_inputs - 1, n_outputs - 1):
        raise ValueError('interface or module grammar mismatch')
    body = header.group(3)
    declarations, assignments = set(), {}
    position = 0
    statement = re.compile(r'\s*(wire\s+([^;]+)|assign\s+([^=;]+)\s*=\s*([^;]+));')
    while position < len(body):
        if not body[position:].strip():
            break
        match = statement.match(body, position)
        if not match:
            raise ValueError('unconsumed body syntax')
        if match.group(2) is not None:
            names = [name.strip() for name in match.group(2).split(',')]
            if any(not re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*', name) for name in names):
                raise ValueError('only scalar declarations are supported')
            for name in names:
                if name in declarations or name in {'x', 'y'}:
                    raise ValueError('duplicate declaration')
                declarations.add(name)
        else:
            lhs, rhs = match.group(3).strip(), match.group(4).strip()
            if lhs in assignments:
                raise ValueError('multiple drivers')
            assignments[lhs] = rhs
        position = match.end()
    outputs = {f'y[{bit}]' for bit in range(n_outputs)}
    if set(assignments) != declarations | outputs:
        raise ValueError('missing or undeclared driver')
    token = re.compile(r"\s*(1'b[01]|[xy]\[[0-9]+\]|[a-zA-Z_][a-zA-Z_0-9]*|[~&^|?:()])")
    parsed = {}
    for lhs, rhs in assignments.items():
        tokens, position = [], 0
        while position < len(rhs):
            match = token.match(rhs, position)
            if not match:
                raise ValueError('unconsumed expression syntax')
            tokens.append(match.group(1)); position = match.end()
        cursor = 0
        def primary():
            nonlocal cursor
            if cursor >= len(tokens):
                raise ValueError('incomplete expression')
            part = tokens[cursor]; cursor += 1
            if part == '~':
                return ('~', primary())
            if part == '(':
                node = expression(0)
                if cursor >= len(tokens) or tokens[cursor] != ')':
                    raise ValueError('unclosed parenthesis')
                cursor += 1
                return node
            if part in {'&', '^', '|', '?', ':', ')'}:
                raise ValueError('unexpected expression token')
            return ('atom', part)
        def expression(minimum):
            nonlocal cursor
            node = primary()
            precedences = {'|': 1, '^': 2, '&': 3}
            while cursor < len(tokens) and tokens[cursor] in precedences and precedences[tokens[cursor]] >= minimum:
                op = tokens[cursor]; cursor += 1
                node = (op, node, expression(precedences[op] + 1))
            if minimum == 0 and cursor < len(tokens) and tokens[cursor] == '?':
                cursor += 1
                high = expression(0)
                if cursor >= len(tokens) or tokens[cursor] != ':':
                    raise ValueError('incomplete conditional')
                cursor += 1
                node = ('?:', node, high, expression(0))
            return node
        parsed[lhs] = expression(0)
        if cursor != len(tokens):
            raise ValueError('unconsumed expression tokens')
    vectors = 1 << n_inputs
    mask = (1 << vectors) - 1
    values = {f'x[{bit}]': sum(1 << x for x in range(vectors) if x & (1 << bit))
              for bit in range(n_inputs)}
    values.update({"1'b0": 0, "1'b1": mask})
    visiting = set()
    def signal(name):
        if name in values:
            return values[name]
        if name not in parsed:
            raise ValueError('undeclared dependency or out-of-range input select')
        if name in visiting:
            raise ValueError('combinational cycle')
        visiting.add(name)
        values[name] = evaluate(parsed[name])
        visiting.remove(name)
        return values[name]
    def evaluate(node):
        op = node[0]
        if op == 'atom':
            return signal(node[1])
        if op == '~':
            return mask ^ evaluate(node[1])
        if op == '&':
            return evaluate(node[1]) & evaluate(node[2])
        if op == '^':
            return evaluate(node[1]) ^ evaluate(node[2])
        if op == '|':
            return evaluate(node[1]) | evaluate(node[2])
        if op == '?:':
            control = evaluate(node[1])
            return (control & evaluate(node[2])) | ((control ^ mask) & evaluate(node[3]))
        raise ValueError('unsupported expression')
    # Audit every declared wire, including disconnected nodes, not just outputs.
    for name in parsed:
        signal(name)
    return [sum(((values[f'y[{bit}]'] >> x) & 1) << bit for bit in range(n_outputs))
            for x in range(vectors)]


class CompactBooleanTest(unittest.TestCase):
    def test_function_work_bounds_count_distinct_calls_and_reject_invalid_caps(self):
        core = "  assign i0 = x[0];\n  assign y[0] = i0;\n"
        # Complements/representatives with the same arguments share one call.
        mappings = [(0, (0, 1), 0), (0, (0, 1), 1), (1, (1, 0), 0)]
        self.assertTrue(reusable_function_within_budget(
            core, mappings, max_statements=2, max_expanded_statements=4))
        self.assertFalse(reusable_function_within_budget(
            core, mappings, max_statements=1, max_expanded_statements=4))
        self.assertFalse(reusable_function_within_budget(
            core, mappings, max_statements=2, max_expanded_statements=3))
        for bad in [-1, True, 1.5, None]:
            with self.assertRaises(ValueError):
                reusable_function_within_budget(core, mappings, max_statements=bad)
            with self.assertRaises(ValueError):
                choose_compact_boolean(1, 1, [0, 1], max_function_expanded_statements=bad)

    def test_tiny_work_cap_preserves_exact_flat_fallback_and_detects_mutation(self):
        rng = random.Random(678341)
        n = 6
        base = [rng.randrange(2) for _ in range(1 << n)]
        words = [sum(base[((x << shift) | (x >> (n - shift))) & 63] << shift
                     for shift in range(n)) for x in range(1 << n)]
        _, reusable, _ = choose_compact_boolean(n, n, words)
        self.assertIn('function', reusable)
        _, flat, _ = choose_compact_boolean(n, n, words, max_function_statements=0)
        _, expanded_cap_flat, _ = choose_compact_boolean(
            n, n, words, max_function_expanded_statements=0)
        self.assertNotRegex(flat, r'\bfunction\b')
        self.assertEqual(flat, expanded_cap_flat)
        self.assertEqual(replay_scalar(flat, n, n), words)
        # Lower both actual representations with the fixed frontend; a syntactically
        # valid output inversion must still fail the complete-domain verifier.
        mutated, count = re.subn(r'(assign y\[0\] = )(.*?);',
                                 r'\1~(\2);', flat, count=1)
        self.assertEqual(count, 1)
        self.assertNotEqual(replay_scalar(mutated, n, n), words)
        with tempfile.TemporaryDirectory() as directory:
            truth, candidate = Path(directory) / 'input.truth', Path(directory) / 'candidate.v'
            truth.write_text('\n'.join(''.join(str((words[63 ^ x] >> bit) & 1)
                                               for x in range(64)) for bit in range(n)) + '\n')
            for source, expected in [(reusable, 'pass'), (flat, 'pass'), (mutated, 'mismatch')]:
                candidate.write_text(source)
                result = verify(truth, candidate, default_yosys(), use_cache=False,
                                frontend_timeout=120, compile_timeout=120, run_timeout=180,
                                replay_workers=1)
                self.assertEqual(result['frontend'], 'pass')
                self.assertEqual(result['status'], expected)
                if expected == 'pass':
                    self.assertEqual(result['vectors'], 64)

    def test_all_orders_exhaustive_random_and_complemented_outputs(self):
        rng = random.Random(732481)
        for n in range(1, 9):
            mask = (1 << 4) - 1
            low = [rng.randrange(mask + 1) for _ in range(1 << n)]
            words = [value | ((value ^ mask) << 4) for value in low]
            orders = [tuple(range(n)), tuple(reversed(range(n)))]
            if n <= 4:
                orders += list(itertools.permutations(range(n)))
            for order in dict.fromkeys(orders):
                for emitter in (emit_compact_robdd, emit_plain_robdd):
                    source, _ = emitter(n, 8, words, order)
                    self.assertEqual(replay_scalar(source, n, 8), words)
            source, _ = emit_factored_anf(n, 8, words)
            self.assertEqual(replay_scalar(source, n, 8), words)

    def test_constants_projections_parity_and_shared_monomials(self):
        n = 7
        for words, m in [([0] * (1 << n), 3), ([7] * (1 << n), 3),
                         ([x & 7 for x in range(1 << n)], 3),
                         ([(x.bit_count() & 1) for x in range(1 << n)], 1),
                         ([((x & 3) == 3) | (((x & 7) == 7) << 1)
                           | (((x & 15) == 15) << 2) for x in range(1 << n)], 3)]:
            family, source, _ = choose_exact_boolean_fallback(n, m, words)
            self.assertIn(family, ['shared ROBDD fallback', 'structural ANF fallback'])
            self.assertEqual(replay_scalar(source, n, m), words)
            self.assertNotRegex(source, r'\b(case|casex|casez|memory)\b')

    def test_full_domain_permutation_reuse_and_complements(self):
        rng = random.Random(873214)
        n = 6
        bases = [[rng.randrange(2) for _ in range(1 << n)] for _ in range(2)]
        permutations = [tuple(range(n)), (5, 2, 4, 0, 1, 3), (2, 1, 5, 4, 0, 3)]
        outputs = []
        for permutation in permutations:
            indices = [0]
            for bit in permutation:
                indices += [index | (1 << bit) for index in indices]
            for base in bases:
                outputs.append([base[index] for index in indices])
        outputs.append([bit ^ 1 for bit in outputs[0]])
        words = [sum(table[x] << bit for bit, table in enumerate(outputs)) for x in range(1 << n)]
        representatives, mappings = find_output_permutations(n, len(outputs), words)
        self.assertEqual(len(representatives), 2)
        packed = [sum(((word >> bit) & 1) << index
                      for index, bit in enumerate(representatives)) for word in words]
        with tempfile.TemporaryDirectory() as directory:
            truth, candidate = Path(directory) / 'input.truth', Path(directory) / 'candidate.v'
            truth.write_text('\n'.join(''.join(str((words[((1 << n) - 1) ^ x] >> bit) & 1)
                                               for x in range(1 << n))
                                      for bit in range(len(outputs))) + '\n')
            for emitter in (emit_compact_robdd, emit_plain_robdd):
                core, _ = emitter(n, len(representatives), packed, tuple(reversed(range(n))))
                source = emit_reusable_function(n, len(outputs), core, representatives, mappings)
                candidate.write_text(source)
                result = verify(truth, candidate, default_yosys(), use_cache=False,
                                frontend_timeout=120, compile_timeout=120, run_timeout=180,
                                replay_workers=1)
                self.assertEqual(result['status'], 'pass')
                self.assertEqual(result['vectors'], 1 << n)

    def test_one_entry_mutation_does_not_invent_permutation_equivalence(self):
        rng = random.Random(239801)
        n = 6
        table = [rng.randrange(2) for _ in range(1 << n)]
        mutated = table.copy(); mutated[17] ^= 1
        words = [a | (b << 1) for a, b in zip(table, mutated)]
        representatives, _ = find_output_permutations(n, 2, words)
        self.assertEqual(representatives, [0, 1])

    def test_bit_permutation_argument_preserves_order_and_coalesces_slices(self):
        self.assertEqual(permutation_argument((0, 1, 2, 3)), 'x')
        self.assertEqual(permutation_argument((2, 3, 0, 1)), '{x[1:0],x[3:2]}')
        self.assertEqual(permutation_argument((3, 2, 1, 0)), '{x[0],x[1],x[2],x[3]}')
        for bad in [(), (0, 0), (1,), (0, 2)]:
            with self.assertRaises(ValueError):
                permutation_argument(bad)

    def test_bad_order_and_incomplete_domains_are_rejected(self):
        for order in [(0, 0), (1,), (2, 0)]:
            with self.assertRaises(ValueError):
                emit_compact_robdd(2, 1, [0, 1, 1, 0], order)
        for words in [[0], [0, 1, 0], [0, 1, 2, 0]]:
            with self.assertRaises(ValueError):
                emit_compact_robdd(2, 1, words, (0, 1))
        with self.assertRaises(ValueError):
            emit_factored_anf(2, 1, [0, 1, 1])

    def test_reversed_orientation_and_output_flip_are_detected(self):
        words = [((x * 3 + 7) ^ (x >> 2)) & 15 for x in range(32)]
        source, _ = emit_compact_robdd(5, 4, words, (4, 2, 0, 3, 1))
        actual = replay_scalar(source, 5, 4)
        self.assertEqual(actual, words)
        self.assertNotEqual(actual, list(reversed(words)))
        self.assertNotEqual(actual, [word ^ 1 for word in words])

    def test_strict_grammar_ports_dependencies_and_cycles(self):
        valid = "module top(input [0:0] x, output [0:0] y); wire a; assign a = x[0]; assign y[0] = a; endmodule"
        self.assertEqual(replay_scalar(valid, 1, 1), [0, 1])
        for bad in [valid.replace('wire a;', 'wire [1:0] a;'),
                    valid.replace('assign a = x[0];', 'assign a = x[1];'),
                    valid.replace('assign a = x[0];', 'assign a = a;'),
                    valid.replace('assign a = x[0];', 'assign a = unknown;'),
                    valid.replace('assign y[0] = a;', ''),
                    valid.replace('endmodule', 'always @* x = 0; endmodule'),
                    valid.replace('assign a = x[0];', 'assign a = x[0] + 1;'),
                    valid.replace('assign a = x[0];', 'assign a = x[0]; assign a = x[0];'),
                    valid.replace('input [0:0] x', 'input [1:0] x'),
                    valid + ' extra']:
            with self.assertRaises(ValueError):
                replay_scalar(bad, 1, 1)

    def test_sharing_reduces_actual_package_cost(self):
        words = [((x * 3) ^ (x >> 2)) & 255 for x in range(256)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.v'
            old, _ = emit_shared_robdd(8, 8, words)
            path.write_text(old)
            old_cost = evaluate_rtl(str(path))[0]
            source, _ = emit_compact_robdd(8, 8, words, tuple(range(8)))
            path.write_text(source)
            new_cost = evaluate_rtl(str(path))[0]
            self.assertLess(new_cost, old_cost)
            self.assertEqual(replay_scalar(source, 8, 8), words)


if __name__ == '__main__':
    unittest.main()

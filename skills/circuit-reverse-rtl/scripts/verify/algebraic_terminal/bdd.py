"""Exact ROBDD discharge of native-gate coefficient functions.

This backend reads original primitive gates directly. It does not lower a
re-emitted coefficient Verilog file or interpret undefined bits as constants.
"""
import hashlib
import json
import re
from pathlib import Path
from .certificate import parse_primitive


class BDD:
    def __init__(self, names, gates, constants, node_cap):
        self.names = names
        self.gates, self.constants, self.node_cap = gates, constants, node_cap
        self.nodes = [None, None]
        self.unique, self.memo, self.signals = {}, {}, {}
        self.pics = {name: self.mk(i, 0, 1) for i, name in enumerate(names)}
        self.active = set()

    def mk(self, variable, low, high):
        if low == high:
            return low
        key = (variable, low, high)
        if key not in self.unique:
            if len(self.nodes) >= self.node_cap:
                raise ValueError('BDD node cap exceeded')
            self.unique[key] = len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    def apply(self, op, left, right):
        # Only the three symmetric truth tables used below are supported.
        if op not in (6, 8, 14):
            raise ValueError('unsupported BDD operation')
        if left <= 1 and right <= 1:
            return (op >> ((left << 1) | right)) & 1
        if left > right:
            left, right = right, left
        key = (op, left, right)
        if key in self.memo:
            return self.memo[key]
        lv = self.nodes[left][0] if left > 1 else len(self.names)
        rv = self.nodes[right][0] if right > 1 else len(self.names)
        variable = min(lv, rv)
        ll, lh = self.nodes[left][1:] if lv == variable else (left, left)
        rl, rh = self.nodes[right][1:] if rv == variable else (right, right)
        result = self.mk(variable, self.apply(op, ll, rl), self.apply(op, lh, rh))
        self.memo[key] = result
        return result

    def signal(self, name):
        if name in self.constants:
            value = self.constants[name]
            if type(value) is not int or value not in (0, 1):
                raise ValueError('non-two-state primitive constant')
            return value
        if name in self.pics:
            return self.pics[name]
        if name in self.signals:
            return self.signals[name]
        if name not in self.gates or name in self.active:
            raise ValueError('undefined, outside-domain, or cyclic gate')
        self.active.add(name)
        op, args = self.gates[name]
        if not args or op not in ('buf', 'not', 'and', 'nand', 'or', 'nor', 'xor', 'xnor'):
            raise ValueError('unsupported primitive gate')
        values = [self.signal(a) for a in args]
        result = values[0]
        if op in ('buf', 'not') and len(values) != 1:
            raise ValueError('invalid unary primitive')
        if op == 'not':
            result = self.apply(6, result, 1)
        elif op != 'buf':
            table = 8 if op in ('and', 'nand') else 14 if op in ('or', 'nor') else 6
            for value in values[1:]:
                result = self.apply(table, result, value)
            if op in ('nand', 'nor', 'xnor'):
                result = self.apply(6, result, 1)
        self.active.remove(name)
        self.signals[name] = result
        return result


def prove(reference, groups_path, domain, node_cap=1000000, order='bit-major'):
    if type(node_cap) is not int or node_cap < 2 or order not in ('bit-major', 'port-major'):
        raise ValueError('invalid BDD resource/order option')
    reference, groups_path = Path(reference), Path(groups_path)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    before = {str(p): sha(p) for p in (reference, groups_path, Path(__file__))}
    gates, inputs, outputs, constants = parse_primitive(reference)
    if len(outputs) != 1 or not domain or not set(domain) <= inputs:
        raise ValueError('invalid complete-word coefficient interface')
    width = len(next(iter(outputs.values())))
    def key(name):
        match = re.fullmatch(r'(.+)\[(\d+)\]', name)
        port, bit = (match[1], int(match[2])) if match else (name, 0)
        return (bit, port) if order == 'bit-major' else (port, bit)
    names = sorted(domain, key=key)
    records = []
    for index, group in enumerate(json.loads(groups_path.read_text())):
        poly = group['polynomial']
        if not poly or any(type(t['coefficient']) is not int or not 0 < t['coefficient'] < (1 << width) for t in poly):
            raise ValueError('noncanonical coefficient polynomial')
        outside = group['outside_primary_monomial']
        if len(outside) != len(set(outside)) or not set(outside) <= inputs - set(domain):
            raise ValueError('invalid outside monomial')
        shift = min((t['coefficient'] & -t['coefficient']).bit_length() - 1 for t in poly)
        reduced_width, manager = width - shift, BDD(names, gates, constants, node_cap)
        modulus = 1 << reduced_width
        columns, constant = [[] for _ in range(reduced_width)], 0
        seen = set()
        for term in poly:
            variables = term['variables']
            frozen = frozenset(variables)
            if len(frozen) != len(variables) or frozen in seen:
                raise ValueError('duplicate/nonmultilinear coefficient term')
            seen.add(frozen)
            bit = 1
            for name in variables:
                bit = manager.apply(8, bit, manager.signal(name))
            coefficient = term['coefficient'] >> shift
            if coefficient >= modulus // 2:
                coefficient -= modulus
            if coefficient < 0:
                constant += coefficient
                bit = manager.apply(6, bit, 1)
                coefficient = -coefficient
            for position in range(reduced_width):
                if (coefficient >> position) & 1:
                    columns[position].append(bit)
        constant %= modulus
        for position in range(reduced_width):
            if (constant >> position) & 1:
                columns[position].append(1)
        for position, terms in enumerate(columns):
            terms[:] = [t for t in terms if t]
            while len(terms) >= 3:
                a, b, c = terms.pop(), terms.pop(), terms.pop()
                ab = manager.apply(6, a, b)
                terms.append(manager.apply(6, ab, c))
                carry = manager.apply(14, manager.apply(8, a, b), manager.apply(8, ab, c))
                if position + 1 < reduced_width:
                    columns[position + 1].append(carry)
            if len(terms) == 2:
                a, b = terms
                value, carry = manager.apply(6, a, b), manager.apply(8, a, b)
                if position + 1 < reduced_width:
                    columns[position + 1].append(carry)
            else:
                value = terms[0] if terms else 0
            if value != 0:
                raise ValueError(f'nonzero coefficient group {index} bit {position}')
        records.append({'group': index, 'bits': reduced_width, 'removed_power_of_two': shift,
                        'all_bits_zero': True, 'bdd_nodes_created': len(manager.nodes)})
    if any(sha(Path(p)) != h for p, h in before.items()):
        raise ValueError('BDD proof source changed')
    return {'status': 'pass', 'equivalent': True, 'engine': 'exact_native_gate_robdd',
            'source_hashes': before, 'node_cap': node_cap, 'variable_order': names,
            'all_coefficient_inputs_free': True, 'groups': records,
            'scope': 'Every grouped coefficient is identically zero; grouping and residual replay are separate mandatory checks.'}

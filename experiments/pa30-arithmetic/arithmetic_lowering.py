#!/usr/bin/env python3
"""Exact generic lowering of unsigned squares and binary constant multipliers.

Operate on Yosys JSON before alumacc. No benchmark IDs or source-pattern tests.
All added arithmetic is unsigned modular arithmetic at the existing Y width.
"""
import argparse
import copy
import json
from pathlib import Path


def integer(value):
    return value if isinstance(value, int) else int(value, 2)


def binary(value):
    return format(value, '032b')


def signed_digits(value):
    sign = -1 if value < 0 else 1
    remaining = abs(value)
    digits = []
    shift = 0
    while remaining:
        if remaining & 1:
            digit = 2 - remaining % 4
            digits.append((shift, sign * digit))
            remaining -= digit
        remaining //= 2
        shift += 1
    assert sum(d * (1 << s) for s, d in digits) == value
    return digits


def known_constant(bits):
    if not all(bit in ('0', '1') for bit in bits):
        return None
    return sum((bit == '1') << i for i, bit in enumerate(bits))


class Builder:
    def __init__(self, module):
        self.module = module
        ids = [bit for entry in module['ports'].values() for bit in entry['bits'] if isinstance(bit, int)]
        ids += [bit for cell in module['cells'].values() for bits in cell['connections'].values() for bit in bits if isinstance(bit, int)]
        ids += [bit for entry in module.get('netnames', {}).values() for bit in entry['bits'] if isinstance(bit, int)]
        self.next_bit = max(ids, default=1) + 1
        self.serial = 0

    def cell(self, kind, a, b=None, y=None, width=None):
        if y is None:
            y = list(range(self.next_bit, self.next_bit + width))
            self.next_bit += width
        self.serial += 1
        name = f'$creas_arith${self.serial}'
        assert name not in self.module['cells']
        connections = {'A': a, 'Y': y}
        parameters = {'A_SIGNED': binary(0), 'A_WIDTH': binary(len(a)), 'Y_WIDTH': binary(len(y))}
        directions = {'A': 'input', 'Y': 'output'}
        if b is not None:
            connections['B'] = b
            parameters.update(B_SIGNED=binary(0), B_WIDTH=binary(len(b)))
            directions['B'] = 'input'
        self.module['cells'][name] = {
            'hide_name': 1, 'type': kind, 'parameters': parameters,
            'attributes': {}, 'port_directions': directions, 'connections': connections,
        }
        return y

    def sum(self, terms, width):
        if not terms:
            return ['0'] * width
        # Balanced modular additions. No intermediate truncation below Y width.
        while len(terms) > 1:
            terms = [self.cell('$add', terms[i], terms[i + 1], width=width)
                     if i + 1 < len(terms) else terms[i]
                     for i in range(0, len(terms), 2)]
        return terms[0]


def lower(net):
    net = copy.deepcopy(net)
    events = []
    for module_name, module in net['modules'].items():
        builder = Builder(module)
        for name, cell in list(module['cells'].items()):
            if cell['type'] != '$mul':
                continue
            parameters = cell['parameters']
            a, b, y = (cell['connections'][p] for p in ('A', 'B', 'Y'))
            width = len(y)
            signed = bool(integer(parameters['A_SIGNED']) and integer(parameters['B_SIGNED']))
            ca, cb = known_constant(a), known_constant(b)
            event = {'module': module_name, 'cell': name, 'a_width': len(a), 'b_width': len(b), 'y_width': width}
            if ca is not None or cb is not None:
                operand, const_bits, coefficient = (b, a, ca) if ca is not None else (a, b, cb)
                if signed and const_bits[-1] == '1':
                    coefficient -= 1 << len(const_bits)
                # Choose an equivalent small signed coefficient modulo 2^Y.
                coefficient %= 1 << width
                if coefficient >= 1 << (width - 1):
                    coefficient -= 1 << width
                extended = (operand + [operand[-1] if signed else '0'] * max(0, width-len(operand)))[:width]
                digits = signed_digits(coefficient)
                positive, negative = [], []
                for shift, digit in digits:
                    term = (['0'] * shift + extended)[:width]
                    (positive if digit > 0 else negative).append(term)
                pos = builder.sum(positive, width)
                neg = builder.sum(negative, width)
                if negative:
                    builder.cell('$sub', pos, neg, y=y)
                else:
                    builder.cell('$pos', pos, y=y)
                event.update(rule='constant_signed_digit', coefficient=coefficient, digits=digits,
                             operand_sign_extended=signed)
            elif a == b and not signed:
                terms = []
                for i, bit in enumerate(a):
                    if 2*i < width:
                        term = ['0'] * width
                        term[2*i] = bit
                        terms.append(term)
                for i, abit in enumerate(a):
                    for j in range(i+1, len(a)):
                        if i+j+1 >= width:
                            continue
                        pair = builder.cell('$and', [abit], [a[j]], width=1)
                        term = ['0'] * width
                        term[i+j+1] = pair[0]
                        terms.append(term)
                builder.cell('$pos', builder.sum(terms, width), y=y)
                event.update(rule='unsigned_symmetric_square', term_count=len(terms))
            else:
                continue
            del module['cells'][name]
            events.append(event)
    return net, events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    net, events = lower(json.loads(args.source.read_text()))
    args.destination.write_text(json.dumps(net) + '\n')
    args.report.write_text(json.dumps({'rules': events}, indent=2) + '\n')


if __name__ == '__main__':
    main()

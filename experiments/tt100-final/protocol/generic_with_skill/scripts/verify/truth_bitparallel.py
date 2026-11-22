#!/usr/bin/env python3
"""Fail-closed complete-domain replay of combinational Yosys JSON cells.

Each Python integer contains one bit for every ordinary input assignment.
This evaluates the exported netlist, not a source-assignment approximation.
Unsupported graphs/cells return unsupported so callers can use another exact
backend; no unsupported result is evidence of equivalence.

Cell semantics follow Yosys techlibs/common/simlib.v. Boolean width/sign
extension and unsigned ripple arithmetic/comparisons are explicit below.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import time


class Unsupported(ValueError):
    pass


UNARY = {'$not', '$pos', '$reduce_and', '$reduce_or', '$reduce_xor',
         '$reduce_xnor', '$reduce_bool', '$logic_not'}
BINARY = {'$and', '$or', '$xor', '$xnor', '$logic_and', '$logic_or',
          '$add', '$sub', '$eq', '$ne', '$lt', '$le', '$gt', '$ge'}
SUPPORTED = UNARY | BINARY | {'$mux', '$concat', '$slice'}


def _parameter(parameters: dict, key: str) -> int:
    value = parameters.get(key)
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value and set(value) <= {'0', '1'}:
        return int(value, 2)
    raise Unsupported(f'invalid or missing parameter {key}')


def _bit(bit: object) -> None:
    if type(bit) is int and bit >= 0:
        return
    if type(bit) is str and bit in {'0', '1'}:
        return
    raise Unsupported(f'X/Z or malformed connection bit {bit!r}')


def _cell_schema(cell: dict) -> tuple[dict, dict]:
    kind = cell.get('type')
    if kind not in SUPPORTED:
        raise Unsupported(f'unsupported cell type {kind}')
    connections = cell.get('connections', {})
    params = cell.get('parameters', {})
    inputs = {'A'} if kind in UNARY or kind == '$slice' else {'A', 'B'}
    if kind == '$mux': inputs.add('S')
    expected_ports = inputs | {'Y'}
    if set(connections) != expected_ports:
        raise Unsupported(f'{kind}: unexpected ports')
    directions = {name: ('output' if name == 'Y' else 'input') for name in expected_ports}
    if cell.get('port_directions') != directions:
        raise Unsupported(f'{kind}: port directions inconsistent with semantics')
    for name, bits in connections.items():
        if not isinstance(bits, list) or not bits:
            raise Unsupported(f'{kind}: empty or malformed port {name}')
        for bit in bits: _bit(bit)
    if kind == '$mux':
        allowed = {'WIDTH'}; width = _parameter(params, 'WIDTH')
        if len(connections['S']) != 1 or any(len(connections[p]) != width for p in ('A', 'B', 'Y')):
            raise Unsupported('$mux: inconsistent widths')
    elif kind == '$concat':
        allowed = {'A_WIDTH', 'B_WIDTH'}
        if len(connections['Y']) != len(connections['A']) + len(connections['B']):
            raise Unsupported('$concat: inconsistent output width')
    else:
        allowed = {'A_WIDTH', 'Y_WIDTH', 'OFFSET'} if kind == '$slice' else {'A_WIDTH', 'Y_WIDTH', 'A_SIGNED'}
        if kind in BINARY: allowed |= {'B_WIDTH', 'B_SIGNED'}
        if kind == '$slice': _parameter(params, 'OFFSET')
        else:
            for key in ('A_SIGNED', 'B_SIGNED') if kind in BINARY else ('A_SIGNED',):
                if _parameter(params, key) not in (0, 1):
                    raise Unsupported(f'{kind}: invalid signedness')
            if kind in {'$add', '$sub', '$eq', '$ne', '$lt', '$le', '$gt', '$ge'}:
                if _parameter(params, 'A_SIGNED') or _parameter(params, 'B_SIGNED'):
                    raise Unsupported(f'{kind}: signed arithmetic/comparison not supported')
    if set(params) != allowed:
        raise Unsupported(f'{kind}: unexpected/missing parameters')
    for name in ('A', 'B', 'Y'):
        key = name + '_WIDTH'
        if key in allowed and _parameter(params, key) != len(connections[name]):
            raise Unsupported(f'{kind}: {name} width disagrees with parameter')
    if any(type(bit) is not int for bit in connections['Y']):
        raise Unsupported(f'{kind}: output attached to a constant')
    return connections, params


def _extend(word: list[int], width: int, signed: bool = False) -> list[int]:
    fill = word[-1] if signed else 0
    return (word + [fill] * max(0, width - len(word)))[:width]


def _reduce(word: list[int], operator: str, universe: int) -> int:
    value = universe if operator == 'and' else 0
    for bit in word:
        if operator == 'and': value &= bit
        elif operator == 'or': value |= bit
        else: value ^= bit
    return value


def _evaluate_cell(cell: dict, ports: dict[str, list[int]], universe: int) -> list[int]:
    kind = cell['type']; params = cell['parameters']; width = len(cell['connections']['Y'])
    a = ports['A']; b = ports.get('B', [])
    if kind == '$mux':
        select = ports['S'][0]
        return [(av & (universe ^ select)) | (bv & select) for av, bv in zip(a, b)]
    if kind == '$concat': return a + b
    if kind == '$slice':
        offset = _parameter(params, 'OFFSET')
        return _extend(a[offset:], width) if offset < len(a) else [0] * width
    if kind in {'$not', '$pos'}:
        value = _extend(a, width, bool(_parameter(params, 'A_SIGNED')))
        return [bit ^ universe for bit in value] if kind == '$not' else value
    if kind.startswith('$reduce_') or kind == '$logic_not':
        operator = 'and' if kind == '$reduce_and' else ('xor' if kind in {'$reduce_xor', '$reduce_xnor'} else 'or')
        value = _reduce(a, operator, universe)
        if kind in {'$reduce_xnor', '$logic_not'}: value ^= universe
        return [value] + [0] * (width - 1)
    if kind in {'$logic_and', '$logic_or'}:
        av = _reduce(a, 'or', universe); bv = _reduce(b, 'or', universe)
        value = av & bv if kind == '$logic_and' else av | bv
        return [value] + [0] * (width - 1)
    if kind in {'$and', '$or', '$xor', '$xnor'}:
        both_signed = bool(_parameter(params, 'A_SIGNED') and _parameter(params, 'B_SIGNED'))
        a = _extend(a, width, both_signed); b = _extend(b, width, both_signed)
        if kind == '$and': return [av & bv for av, bv in zip(a, b)]
        if kind == '$or': return [av | bv for av, bv in zip(a, b)]
        values = [av ^ bv for av, bv in zip(a, b)]
        return [bit ^ universe for bit in values] if kind == '$xnor' else values
    if kind in {'$add', '$sub'}:
        a = _extend(a, width); b = _extend(b, width)
        carry = 0
        if kind == '$sub': b = [bit ^ universe for bit in b]; carry = universe
        output = []
        for av, bv in zip(a, b):
            combined = av ^ bv; output.append(combined ^ carry)
            carry = (av & bv) | (combined & carry)
        return output
    if kind in {'$eq', '$ne', '$lt', '$le', '$gt', '$ge'}:
        size = max(len(a), len(b)); a = _extend(a, size); b = _extend(b, size)
        equal = universe; less = 0
        for av, bv in reversed(list(zip(a, b))):
            less |= equal & (av ^ universe) & bv
            equal &= (av ^ bv) ^ universe
        if kind == '$eq': value = equal
        elif kind == '$ne': value = equal ^ universe
        elif kind == '$lt': value = less
        elif kind == '$le': value = less | equal
        elif kind == '$gt': value = (less | equal) ^ universe
        else: value = less ^ universe
        return [value] + [0] * (width - 1)
    raise Unsupported(f'unimplemented cell {kind}')


def check_json(truth: str | Path, frontend_json: str | Path, *, max_inputs: int = 18,
               max_cells: int = 100000) -> dict:
    """Return pass, mismatch, or unsupported; only pass proves equivalence."""
    truth = Path(truth); frontend_json = Path(frontend_json); start = time.monotonic()
    result = dict(status='unsupported', verification_method='complete-domain bit-parallel replay of Yosys JSON cells')
    try:
        result.update(truth_sha256=hashlib.sha256(truth.read_bytes()).hexdigest(),
                      frontend_json_sha256=hashlib.sha256(frontend_json.read_bytes()).hexdigest())
        lines = [line.strip() for line in truth.read_text().splitlines() if line.strip()]
        if not lines: raise Unsupported('empty truth table')
        count = len(lines[0]); n = count.bit_length() - 1; m = len(lines)
        if n < 1 or n > max_inputs or count != 1 << n:
            raise Unsupported('truth input dimension outside full-domain resource bound')
        if any(len(line) != count or set(line) - {'0', '1'} for line in lines):
            raise Unsupported('malformed truth table')
        result.update(n_inputs=n, n_outputs=m, vectors=count)
        design = json.loads(frontend_json.read_text()); modules = design.get('modules', {})
        if set(modules) != {'top'}: raise Unsupported('hierarchical or missing top module')
        module = modules['top']; ports = module.get('ports', {})
        if module.get('memories') or module.get('processes'):
            raise Unsupported('unlowered process or memory in module')
        attributes = module.get('attributes', {})
        if any(str(attributes.get(key, 0)).strip('0') for key in ('blackbox', 'whitebox')):
            raise Unsupported('opaque top module')
        if set(ports) != {'x', 'y'}: raise Unsupported('top must have exactly x and y ports')
        for name, direction, width in (('x', 'input', n), ('y', 'output', m)):
            port = ports[name]
            if (port.get('direction') != direction or len(port.get('bits', [])) != width
                    or port.get('offset', 0) != 0 or port.get('upto', 0) != 0 or port.get('signed', 0) != 0):
                raise Unsupported(f'invalid {name} interface width/orientation/signedness')
            for bit in port['bits']: _bit(bit)
        inputs = ports['x']['bits']; outputs = ports['y']['bits']
        if any(type(bit) is not int for bit in inputs) or len(set(inputs)) != n:
            raise Unsupported('input aliases or constant inputs')
        cells = module.get('cells', {})
        if not isinstance(cells, dict) or len(cells) > max_cells:
            raise Unsupported('cell graph outside resource bound')
        schemas = {}; drivers = {bit: None for bit in inputs}
        referenced = set(outputs)
        for name, cell in cells.items():
            connections, params = _cell_schema(cell); schemas[name] = connections
            for port, bits in connections.items():
                referenced.update(bits)
                if port == 'Y':
                    for bit in bits:
                        if bit in drivers: raise Unsupported(f'multiple drivers for bit {bit}')
                        drivers[bit] = name
        for data in module.get('netnames', {}).values():
            for bit in data.get('bits', []): _bit(bit); referenced.add(bit)
        for bit in referenced:
            _bit(bit)
            if type(bit) is int and bit not in drivers: raise Unsupported(f'undriven bit {bit}')
        dependents = {name: set() for name in cells}; indegree = {}
        for name, connections in schemas.items():
            dependencies = set()
            for port, bits in connections.items():
                if port == 'Y': continue
                dependencies.update(drivers[bit] for bit in bits
                                    if type(bit) is int and drivers[bit] is not None)
            indegree[name] = len(dependencies)
            for dependency in dependencies: dependents[dependency].add(name)
        queue = deque(name for name in cells if not indegree[name]); ordered = []
        while queue:
            name = queue.popleft(); ordered.append(name)
            for child in dependents[name]:
                indegree[child] -= 1
                if indegree[child] == 0: queue.append(child)
        if len(ordered) != len(cells): raise Unsupported('cyclic combinational graph')
        universe = (1 << count) - 1; values = {}
        for bit_index, bit in enumerate(inputs):
            block = 1 << bit_index
            values[bit] = int(('1' * block + '0' * block) * (count // (block * 2)), 2)
        def get(bit):
            return (0 if bit == '0' else universe) if type(bit) is str else values[bit]
        for name in ordered:
            connections = schemas[name]
            word_ports = {port: [get(bit) for bit in bits]
                          for port, bits in connections.items() if port != 'Y'}
            computed = _evaluate_cell(cells[name], word_ports, universe)
            if len(computed) != len(connections['Y']): raise Unsupported('cell output coverage failure')
            values.update(zip(connections['Y'], computed))
        actual = [get(bit) for bit in outputs]
        # int(line,2) bit x is line[count-1-x], exactly the complemented -xf
        # input index. No per-source-assignment grammar is used here.
        expected = [int(line, 2) for line in lines]
        differences = 0
        for av, ev in zip(actual, expected): differences |= av ^ ev
        result.update(cells_evaluated=len(ordered), cell_types=dict(Counter(c['type'] for c in cells.values())))
        if differences:
            index = (differences & -differences).bit_length() - 1
            got = sum(((word >> index) & 1) << bit for bit, word in enumerate(actual))
            wanted = sum(((word >> index) & 1) << bit for bit, word in enumerate(expected))
            result.update(status='mismatch', index=index, got=hex(got), expected=hex(wanted))
        else: result['status'] = 'pass'
    except (Unsupported, OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        result.update(status='unsupported', reason=str(error))
    result['wall_seconds'] = time.monotonic() - start
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('truth', type=Path); parser.add_argument('frontend_json', type=Path)
    args = parser.parse_args(); result = check_json(args.truth, args.frontend_json)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result['status'] == 'pass' else 1)

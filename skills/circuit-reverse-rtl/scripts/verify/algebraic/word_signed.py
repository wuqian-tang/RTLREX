"""Exact modular lowering of range-checked signed arithmetic RTLIL cells.

An internal signed value can be lifted only when interval arithmetic proves
that its native two's-complement result cannot overflow. Unsupported slices,
shifts, controls, and ambiguous signedness fail closed.
"""


def word_poly_signed(design, width, bound_records=None, output_bounds=None):
    modulus = 1 << width
    primary = {}
    drivers = {}
    for name, port in design['ports'].items():
        assert not any(port.get(k, 0) for k in ('offset', 'upto', 'signed'))
        if port['direction'] == 'input':
            for index, bit in enumerate(port['bits']):
                assert isinstance(bit, int) and bit not in primary
                primary[bit] = name if len(port['bits']) == 1 else f'{name}[{index}]'
    for cell in design['cells'].values():
        if 'Y' in cell.get('connections', {}):
            key = tuple(cell['connections']['Y'])
            assert key not in drivers
            drivers[key] = cell

    def add(lhs, rhs, factor=1):
        result = lhs.copy()
        for term, coefficient in rhs.items():
            value = (result.get(term, 0) + factor * coefficient) % modulus
            if value:
                result[term] = value
            else:
                result.pop(term, None)
        return result

    def multiply(lhs, rhs):
        result = {}
        for a, x in lhs.items():
            for b, y in rhs.items():
                key = a | b
                result[key] = (result.get(key, 0) + x * y) % modulus
                if not result[key]:
                    del result[key]
        return result

    def domain(size, signed):
        return (-(1 << (size - 1)), (1 << (size - 1)) - 1) if signed else (0, (1 << size) - 1)

    def parameter(cell, key):
        return int(cell.get('parameters', {}).get(key, '0'), 2)

    memo, active = {}, set()

    def bus(bits, signed=False):
        bits = tuple(bits)
        key = (bits, signed)
        assert bits and key not in active, 'empty bus or cyclic candidate'
        if key in memo:
            return memo[key]
        active.add(key)
        size = len(bits)
        if all(bit in primary or bit in ('0', '1') for bit in bits):
            poly, lo, hi = {}, 0, 0
            # Combine repeated PI weights before bounding, e.g. sign extension.
            weights = {}
            constant = 0
            for index, bit in enumerate(bits):
                coefficient = -(1 << index) if signed and index == size - 1 else 1 << index
                if bit == '1':
                    constant += coefficient
                elif bit != '0':
                    weights[primary[bit]] = weights.get(primary[bit], 0) + coefficient
            if constant % modulus:
                poly[frozenset()] = constant % modulus
            lo = hi = constant
            for name, coefficient in weights.items():
                if coefficient % modulus:
                    poly[frozenset([name])] = coefficient % modulus
                lo += min(0, coefficient)
                hi += max(0, coefficient)
        elif bits in drivers:
            cell = drivers[bits]
            connections = cell['connections']
            assert cell['type'] in ('$add', '$sub', '$mul'), ('unsupported signed-path cell', cell['type'])
            assert parameter(cell, 'Y_WIDTH') == size
            a_signed, b_signed = parameter(cell, 'A_SIGNED'), parameter(cell, 'B_SIGNED')
            assert a_signed == b_signed and a_signed in (0, 1), 'mixed cell signedness unsupported'
            assert parameter(cell, 'A_WIDTH') == len(connections['A'])
            assert parameter(cell, 'B_WIDTH') == len(connections['B'])
            a, al, ah = bus(connections['A'], bool(a_signed))
            b, bl, bh = bus(connections['B'], bool(b_signed))
            if cell['type'] == '$add':
                poly, lo, hi = add(a, b), al + bl, ah + bh
            elif cell['type'] == '$sub':
                poly, lo, hi = add(a, b, -1), al - bh, ah - bl
            else:
                products = (al * bl, al * bh, ah * bl, ah * bh)
                poly, lo, hi = multiply(a, b), min(products), max(products)
            minimum, maximum = domain(size, signed)
            if size < width:
                assert minimum <= lo <= hi <= maximum, 'native signed/unsigned result can wrap before extension'
                if bound_records is not None:
                    bound_records.append({'cell_type': cell['type'], 'native_width': size,
                                          'interpreted_signed': signed, 'range_min': lo,
                                          'range_max': hi, 'comparison_ring_width': width})
            else:
                # Native wrap and signed interpretation differ by multiples of
                # 2**size, invisible in the comparison ring of width <= size.
                if not minimum <= lo <= hi <= maximum:
                    lo, hi = minimum, maximum
        else:
            matches = []
            for driven in drivers:
                if len(driven) >= size or bits[:len(driven)] != driven:
                    continue
                extension = bits[len(driven):]
                if all(bit == '0' for bit in extension):
                    matches.append((driven, False))
                elif all(bit == driven[-1] for bit in extension):
                    matches.append((driven, True))
            assert len(matches) == 1, 'unsupported signed-path internal slice/extension'
            driven, sign_extend = matches[0]
            poly, lo, hi = bus(driven, sign_extend)
            if sign_extend and not signed and lo < 0:
                assert size >= width, 'unsigned interpretation of narrow negative extension unsupported'
                lo, hi = domain(size, False)
            # A zero-extended native value is nonnegative even when the wider
            # bus is interpreted as signed. Sign extension preserves value.
        active.remove(key)
        memo[key] = (poly, lo, hi)
        return memo[key]

    result = {}
    for name, port in design['ports'].items():
        if port['direction'] == 'output':
            poly, _, upper = bus(port['bits'])
            result[name] = poly
            if output_bounds is not None:
                output_bounds[name] = upper
    return result, set(primary.values())

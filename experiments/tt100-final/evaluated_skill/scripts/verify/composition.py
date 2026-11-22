#!/usr/bin/env python3
"""Strict composition over two combinational AIGs and an explicit proof plan.

The plan supplies hypotheses, never trusted facts: reference tap literals, a
pi->po bridge, and a pi->po word stage. Every bridge bit, reconnection, word-stage
output and remaining original output is checked. Input/output AIG symbols must
match exactly. Optional original_reference/original_candidate hash records add
strict full-interface bridges from each original RTL to its supplied AIG.

Plan schema: reference_aig/candidate_aig/bridge_rtl/word_stage_rtl are {path,
sha256}; tap_literals is a list of reference AIG literals in bridge-output order;
word_outputs lists distinct original output indices in word-stage order.
Bridge top: input pi[I-1:0], output po[T-1:0]. Word top: input pi[I+T-1:0],
output po[W-1:0], where low I bits are original inputs and high T bits are taps.
No case-specific formula or assumed relation is built into this verifier.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import os
import signal
import sys
import time


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def read_aig(path):
    data = Path(path).read_bytes()
    head, rest = data.split(b'\n', 1)
    fields = head.split()
    require(len(fields) == 6 and fields[0] == b'aig', 'only plain binary AIGER supported')
    m, ni, nl, no, na = map(int, fields[1:])
    require(nl == 0 and m == ni + na and ni > 0 and no > 0, 'invalid combinational AIG dimensions')
    pos = 0
    outputs = []
    for _ in range(no):
        end = rest.index(b'\n', pos)
        outputs.append(int(rest[pos:end])); pos = end + 1
    def delta():
        nonlocal pos
        value = shift = 0
        while True:
            require(pos < len(rest) and shift <= 63, 'invalid AIG delta')
            byte = rest[pos]; pos += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
            shift += 7
    gates = []
    for node in range(ni + 1, m + 1):
        a = 2 * node - delta(); b = a - delta()
        require(0 <= b <= a < 2 * node, 'non-topological AIG')
        gates.append((a, b))
    require(all(0 <= x <= 2 * m + 1 for x in outputs), 'output literal out of range')
    symbols = {'i': {}, 'o': {}}
    for line in rest[pos:].decode().splitlines():
        if line == 'c':
            break
        match = re.fullmatch(r'([io])(\d+) (.+)', line)
        require(match is not None, 'unsupported AIG symbol')
        kind, idx, name = match.groups(); idx = int(idx)
        require(idx not in symbols[kind], 'duplicate symbol')
        symbols[kind][idx] = name
    require(set(symbols['i']) == set(range(ni)) and set(symbols['o']) == set(range(no)), 'complete interface symbols required')
    require(len(set(symbols['i'].values())) == ni and len(set(symbols['o'].values())) == no, 'nonunique interface symbols')
    return dict(I=ni, O=no, M=m, outputs=outputs, gates=gates, symbols=symbols)


def emit(graph, path, outputs, cut_literals=()):
    """Primitive gate projection; each cut literal equals a fresh high pi bit."""
    require(outputs and all(type(x) is int and 0 <= x <= 2 * graph['M'] + 1 for x in outputs), 'invalid projection literal')
    ni = graph['I']; total = ni + len(cut_literals)
    cuts = {literal >> 1: (ni + i, literal & 1) for i, literal in enumerate(cut_literals)}
    require(len(cuts) == len(cut_literals), 'cut nodes must be distinct')
    require(all(ni < node <= graph['M'] for node in cuts), 'cuts must name internal nodes')
    lines = ['module top(pi,po);', f'input [{total-1}:0] pi;', f'output [{len(outputs)-1}:0] po;']
    def var(node):
        return "1'b0" if node == 0 else f'pi[{node-1}]' if node <= ni else f'n{node}'
    def literal(value):
        return f'neg{value>>1}' if value & 1 else var(value >> 1)
    for node in range(ni + 1, graph['M'] + 1):
        lines.append(f'wire n{node};')
    negative = {x >> 1 for pair in graph['gates'] for x in pair if x & 1} | {x >> 1 for x in outputs if x & 1}
    for node in sorted(negative):
        lines.append(f'wire neg{node}; not inv{node}(neg{node}, {var(node)});')
    for node, (a, b) in enumerate(graph['gates'], ni + 1):
        if node in cuts:
            index, phase = cuts[node]
            lines.append(f'{"not" if phase else "buf"} cut{node}(n{node}, pi[{index}]);')
        else:
            lines.append(f'and gate{node}(n{node}, {literal(a)}, {literal(b)});')
    for i, value in enumerate(outputs):
        lines.append(f'buf out{i}(po[{i}], {literal(value)});')
    lines.append('endmodule')
    Path(path).write_text('\n'.join(lines) + '\n')


def contract(path, inputs, outputs):
    from verify.algebraic.certificate import source_contract
    # Compare against an explicit contract fixture; no reliance on dict shape.
    fixture = Path(path).parent / (Path(path).stem + '_contract.v')
    fixture.write_text(f'module top(pi,po); input [{inputs-1}:0] pi; output [{outputs-1}:0] po; endmodule\n')
    require(source_contract(path) == source_contract(fixture), 'stage interface does not match plan: ' + str(path))


def run_command(command, folder, timeout):
    folder.mkdir(parents=True, exist_ok=True)
    save(folder / 'command.json', command)
    start = time.monotonic()
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        from verify.cec import stop_process_group
        stdout, stderr = stop_process_group(process)
        (folder / 'stdout.txt').write_text(stdout)
        (folder / 'stderr.txt').write_text(stderr)
        save(folder / 'execution.json', {'returncode': process.returncode,
             'seconds': time.monotonic() - start, 'timed_out': True})
        raise TimeoutError('bounded proof process exceeded limit') from exc
    (folder / 'stdout.txt').write_text(stdout)
    (folder / 'stderr.txt').write_text(stderr)
    save(folder / 'execution.json', {'returncode': process.returncode, 'seconds': time.monotonic() - start})
    require(process.returncode == 0, 'proof/lowering process did not succeed: ' + str(folder))
    return stdout


def sat(reference, candidate, folder, timeout, checker):
    stdout = run_command([sys.executable, str(checker), str(reference), str(candidate), '--engine', 'auto', '--strict-cec', '--timeout', str(timeout), '--abc-timeout', str(timeout), '--tmpdir', str(folder), '--keep-tmp', '--json'], folder, 3 * timeout + 90)
    result = json.loads(stdout)
    require(result.get('status') == 'pass' and result.get('equivalent') is True, 'strict SAT stage did not pass')
    lowered = list(folder.glob('*/ref.aig'))
    require(len(lowered) == 1, 'unique retained lowering artifacts required')
    lhs = read_aig(lowered[0]); rhs = read_aig(lowered[0].with_name('impl.aig'))
    require(lhs['symbols'] == rhs['symbols'], 'lowered combinational stage interfaces differ')
    result['combinational_lowering_checked'] = True
    result['lowered_sha256'] = [sha(lowered[0]), sha(lowered[0].with_name('impl.aig'))]
    save(folder / 'result.json', result)
    return result


def algebraic_worker(reference, candidate, folder, yosys, cap):
    from verify.algebraic import cuts, certificate
    identities = cuts.extract(reference, 48)
    identity_path = folder / 'identities.json'; save(identity_path, identities)
    item = {'input_path': str(reference), 'candidate_path': str(candidate), 'input_sha256': sha(reference), 'candidate_sha256': sha(candidate)}
    # opt_clean preserves the word-cell widths supplied by the plan.
    result = certificate.verify(item, identity_path, folder / 'replay', yosys=yosys, term_cap=cap, optimize_word=False)
    require(result.get('status') == 'strict_algebraic_equivalence' and result.get('all_original_outputs_compared') is True, 'incomplete algebraic stage')
    save(folder / 'result.json', result)


def prove_stage(reference, candidate, folder, yosys, timeout, cap, engine, sliced=()):
    """Choose a verifier, without changing the stage's complete proof duty."""
    require(engine in ('auto', 'algebraic', 'algebraic-cones'), 'unsupported stage engine')
    checker = Path(__file__).with_name('cec.py')
    if engine == 'auto':
        return sat(reference, candidate, folder, timeout, checker)
    command = [sys.executable, str(checker), str(reference), str(candidate),
               '--engine', engine, '--strict-cec', '--algebraic-timeout', str(timeout),
               '--algebraic-term-cap', str(cap), '--keep-tmp', '--tmpdir', str(folder), '--json']
    for name in sliced:
        require(isinstance(name, str) and re.fullmatch(r'\w+', name), 'invalid sliced output name')
        command.extend(['--algebraic-sliced-output', name])
    result = json.loads(run_command(command, folder, timeout + 10))
    require(result.get('status') == 'pass' and result.get('equivalent') is True,
            'arithmetic stage did not prove all outputs')
    records = list(folder.glob('*/proof/result.json'))
    require(len(records) == 1, 'one complete arithmetic record required')
    proof = json.loads(records[0].read_text())
    require(proof.get('strict') is True and proof.get('all_outputs_compared') is True,
            'incomplete arithmetic scope')
    save(folder / 'result.json', result)
    return result


def bind_original(source, graph, folder, timeout):
    """CEC-bind a pinned AIG to its original RTL with an audited named adapter.

    The adapter is generated here, never supplied by the proof plan. Current
    support is the same explicit, zero-based descending interface as algebraic
    replay; unsupported signed/ascending ports fail closed.
    """
    from verify.algebraic.certificate import source_contract
    contract = source_contract(source)
    expected = {d: {n if w == 1 else f'{n}[{i}]'
                    for n, direction, w, _, _ in contract if direction == d for i in range(w)}
                for d in ('input', 'output')}
    require(set(graph['symbols']['i'].values()) == expected['input'] and
            set(graph['symbols']['o'].values()) == expected['output'], 'original interface bit coverage differs')
    folder.mkdir(parents=True, exist_ok=False)
    flat = folder / 'aig.v'; emit(graph, flat, graph['outputs'])
    text, count = re.subn(r'\bmodule\s+top\b', 'module proof_original_aig', flat.read_text())
    require(count == 1, 'unexpected projection module')
    names = [c[0] for c in contract]
    lines = [text, 'module top(' + ','.join(names) + ');']
    for n, direction, width, _, _ in contract:
        lines.append(f'{direction} [{width-1}:0] {n};')
    lines.extend([f'wire [{graph["I"]-1}:0] pi;', f'wire [{graph["O"]-1}:0] po;'])
    for i, name in graph['symbols']['i'].items(): lines.append(f'assign pi[{i}] = {name};')
    for i, name in graph['symbols']['o'].items(): lines.append(f'assign {name} = po[{i}];')
    lines.extend(['proof_original_aig dut(.pi(pi),.po(po));', 'endmodule'])
    adapter = folder / 'adapter.v'; adapter.write_text('\n'.join(lines) + '\n')
    return sat(source, adapter, folder / 'proof', timeout, Path(__file__).with_name('cec.py'))


def split_tap_words(reference, candidate, widths, folder):
    """Expose every tap bit in independently checked word-sized groups."""
    require(widths and all(type(w) is int and w > 0 for w in widths), 'invalid tap word widths')
    names = [f'__cec_tap_word_{i}' for i in range(len(widths))]
    mapping = {}; offset = 0
    for name, width in zip(names, widths):
        for i in range(width): mapping[offset + i] = f'{name}[{i}]'
        offset += width
    files = []
    for original, primitive in [(reference, True), (candidate, False)]:
        text = original.read_text()
        require(all(re.search(r'\b'+n+r'\b', text) is None for n in names), 'tap projection name collision')
        text, count = re.subn(r'\bmodule\s+top\s*\(\s*pi\s*,\s*po\s*\)',
                              'module top(pi,'+','.join(names)+')', text)
        require(count == 1, 'unsupported tap header')
        decl = '\n'.join(f'output [{w-1}:0] {n};' for n,w in zip(names,widths))
        text, count = re.subn(r'\boutput\s*\[\s*'+str(offset-1)+r'\s*:\s*0\s*\]\s*po\s*;',
                              decl if primitive else decl+f'\nwire [{offset-1}:0] po;', text)
        require(count == 1, 'tap groups must cover the complete output bus')
        if primitive:
            text = re.sub(r'\bpo\[(\d+)\]', lambda m:mapping[int(m[1])], text)
        else:
            offset = 0; assignments=[]
            for n,w in zip(names,widths):
                assignments.append(f'assign {n} = po[{offset+w-1}:{offset}];');offset += w
            text = text.replace('endmodule', '\n'.join(assignments)+'\nendmodule')
        target = folder / (original.stem+'_grouped.v');target.write_text(text);files.append(target)
    return *files, names


def verify(plan_path, out, yosys, timeout, cap):
    verifier_hash = sha(__file__)
    plan = json.loads(plan_path.read_text()); save(out / 'plan.json', plan)
    frozen = {}
    for key in ('reference_aig', 'candidate_aig', 'bridge_rtl', 'word_stage_rtl'):
        record = plan[key]; path = Path(record['path']).resolve()
        require(sha(path) == record['sha256'], 'artifact hash mismatch: ' + key)
        frozen[key] = path
    a = read_aig(frozen['reference_aig']); b = read_aig(frozen['candidate_aig'])
    require(a['symbols'] == b['symbols'], 'original ordered interfaces differ')
    originals = {}
    if 'original_reference' in plan or 'original_candidate' in plan:
        require('original_reference' in plan and 'original_candidate' in plan, 'both original RTL sources required')
        from verify.algebraic.certificate import source_contract
        for key, graph in [('original_reference', a), ('original_candidate', b)]:
            record = plan[key]; source = Path(record['path']).resolve()
            require(sha(source) == record['sha256'], 'original RTL hash mismatch')
            originals[key] = source
        require(source_contract(originals['original_reference']) == source_contract(originals['original_candidate']),
                'original RTL contracts differ')
        for key, graph in [('original_reference', a), ('original_candidate', b)]:
            bind_original(originals[key], graph, out / key, timeout)
    taps = plan['tap_literals']; selected = plan['word_outputs']
    require(taps and all(type(x) is int for x in taps), 'nonempty integer tap list required')
    require(selected and all(type(x) is int for x in selected), 'nonempty integer output list required')
    require(len(set(selected)) == len(selected) and all(0 <= x < a['O'] for x in selected), 'invalid word output selection')
    # Copy supplied modules into the immutable proof directory before checking.
    bridge = out / 'bridge.v'; bridge.write_bytes(frozen['bridge_rtl'].read_bytes())
    word = out / 'word.v'; word.write_bytes(frozen['word_stage_rtl'].read_bytes())
    contract(bridge, a['I'], len(taps)); contract(word, a['I'] + len(taps), len(selected))
    checker = Path(__file__).with_name('cec.py')
    source_taps = out / 'source_taps.v'; emit(a, source_taps, taps)
    tap_reference, tap_candidate = source_taps, bridge
    sliced = plan.get('tap_sliced_outputs', [])
    if 'tap_word_widths' in plan:
        require(sum(plan['tap_word_widths']) == len(taps), 'tap groups omit output bits')
        tap_reference, tap_candidate, sliced = split_tap_words(source_taps, bridge, plan['tap_word_widths'], out)
    prove_stage(tap_reference, tap_candidate, out / 'tap_proof', yosys, timeout, cap, plan.get('tap_engine', 'auto'), sliced)
    source_word = out / 'source_word.v'; emit(a, source_word, [a['outputs'][i] for i in selected], taps)
    if 'word_engine' in plan:
        prove_stage(source_word, word, out / 'word_proof', yosys, timeout, cap, plan['word_engine'])
    else:
        algebraic = out / 'word_proof'; algebraic.mkdir()
        run_command([sys.executable, str(Path(__file__).resolve()), '--algebraic-worker', str(source_word), str(word), str(algebraic), str(yosys), str(cap)], algebraic, timeout)
    # Reconnect exactly the previously proved bridge to the supplied word stage.
    def rename(path, name):
        text = path.read_text()
        text, count = re.subn(r'\bmodule\s+top\b', 'module ' + name, text)
        require(count == 1 and len(re.findall(r'\bmodule\b', text)) == 1, 'exactly one top module required')
        return text
    reconnect = out / 'reconnected.v'
    reconnect.write_text(rename(bridge, 'proof_bridge') + '\n' + rename(word, 'proof_word') + f'\nmodule top(pi,po); input [{a["I"]-1}:0] pi; output [{len(selected)-1}:0] po; wire [{len(taps)-1}:0] taps; proof_bridge br(.pi(pi),.po(taps)); proof_word wd(.pi({{taps,pi}}),.po(po)); endmodule\n')
    flat = out / 'reconnected_flat.v'
    run_command([str(yosys), '-q', '-p', f'read_verilog {reconnect}; hierarchy -check -top top; proc; flatten -noscopeinfo; opt_clean; check -assert; write_verilog -noattr {flat}'], out / 'reconnect_lower', timeout)
    target_word = out / 'candidate_word.v'; emit(b, target_word, [b['outputs'][i] for i in selected])
    sat(target_word, flat, out / 'reconnect_proof', timeout, checker)
    remaining = [i for i in range(a['O']) if i not in selected]
    if remaining:
        reference_residual = out / 'reference_residual.v'; candidate_residual = out / 'candidate_residual.v'
        emit(a, reference_residual, [a['outputs'][i] for i in remaining], [a['outputs'][i] for i in selected])
        emit(b, candidate_residual, [b['outputs'][i] for i in remaining], [b['outputs'][i] for i in selected])
        sat(reference_residual, candidate_residual, out / 'residual_proof', timeout, checker)
    require(set(selected) | set(remaining) == set(range(a['O'])), 'original output coverage incomplete')
    for key, path in frozen.items():
        require(sha(path) == plan[key]['sha256'], 'input changed during verification')
    for key, path in originals.items():
        require(sha(path) == plan[key]['sha256'], 'original RTL changed during verification')
    require(sha(__file__) == verifier_hash, 'composition verifier changed during proof')
    return {'status': 'pass', 'equivalent': True, 'strict': True, 'certified_domain': 'hash-bound original RTL pair' if originals else 'supplied combinational AIGs with matching ordered symbols', 'original_rtl_bound': bool(originals), 'all_original_outputs_compared': True, 'original_input_bits': a['I'], 'original_output_bits': a['O'], 'proved_taps': len(taps), 'word_outputs': selected, 'remaining_outputs': remaining, 'original_artifacts': plan, 'verifier_sha256': verifier_hash}


def main():
    require(__debug__, 'python -O cannot certify')
    if len(sys.argv) > 1 and sys.argv[1] == '--algebraic-worker':
        algebraic_worker(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]), int(sys.argv[6])); return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--yosys', type=Path, required=True); parser.add_argument('--timeout', type=int, default=120); parser.add_argument('--term-cap', type=int, default=200000)
    args = parser.parse_args(); start = time.monotonic()
    require(args.timeout > 0 and args.term_cap > 0, 'resource limits must be positive')
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        result = verify(args.plan.resolve(), args.out.resolve(), args.yosys.resolve(), args.timeout, args.term_cap)
    except Exception as exc:
        result = {'status': 'unknown', 'equivalent': None, 'strict': False, 'reason': f'{type(exc).__name__}: {exc}'}
    result['seconds'] = time.monotonic() - start
    if args.out.exists(): save(args.out / 'result.json', result)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result['equivalent'] is True else 1)

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()

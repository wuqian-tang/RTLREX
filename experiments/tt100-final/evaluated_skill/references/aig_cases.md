# Complete AIG cofactor proofs

`verify/aig_cases.py` proves one complete two-state combinational AIG pair. It preserves every input and output symbol and partitions **all** assignments to 1–12 explicitly named primary-input bits. Every branch must pass ABC CEC. Missing branches, solver errors, timeouts, and incomplete interfaces remain unproved.

```bash
python3 scripts/verify/aig_cases.py \
  --reference-aig reference.aig --candidate-aig candidate.aig \
  --split-input 'operand[0]' --split-input 'operand[1]' \
  --out proof --jobs 4 --branch-timeout 30 --timeout 900
```

The first split input is the least significant bit of the cube index. The output `archive.json` records the two source hashes, the ordered split symbols, and every cube's cofactor files, solver log, and exit code. The checker independently reconstructs Boolean DAG identities for each cofactor: it verifies the complete source graph under that cube against the retained cofactor, including every output. Canonical DAG reduction uses only exact AND, inversion, constant, and duplicate-input identities.

To check an existing complete archive:

```bash
python3 scripts/verify/aig_cases.py \
  --reference-aig reference.aig --candidate-aig candidate.aig \
  --split-input 'operand[0]' --split-input 'operand[1]' \
  --replay-manifest previous-proof/archive.json --out replay --timeout 900
```

Replay verifies all hashes, the complete ordered cube coverage, each independent DAG identity, and every archived solver outcome. Its result explicitly identifies **archived solver replay with a fresh cofactor audit**; it does not claim fresh solver execution. The archive schema is `aig-cases/v1`; each branch contains `index`, `{path,sha256}` records for `reference`, `candidate`, and `solver_log`, and the solver's integer `returncode`. A pass log cannot override a nonzero exit code or a counterexample/error in the same log.

## Scope and composition

A pass covers only the complete supplied AIG pair. To claim equivalence of original RTL, independently prove and retain both original-RTL-to-AIG bridges with full named input/output coverage (for example, `verify.composition.bind_original`). To use an internal word projection, additionally verify its exact source taps, prove every cut relation, preserve aliases, and close the complete residual. An AIG projection proof or a subset of cubes is never a complete original-circuit certificate.

The command owns a whole-process-group watchdog; `--worker` is an internal implementation argument. The artifact records checker and AIG-reader hashes. The frontend accepts plain binary combinational AIGER with complete, matching symbols; latches and partial interfaces are rejected.

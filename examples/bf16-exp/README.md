# BF16 exponential running example

This directory contains the actual initial and rewritten RTL from the paper's
`ex200` running example. Both files are byte-identical to the original experiment
candidates. The 16-bit input and 16-bit output use BF16 encoding. The original
truth table is in [`benchmarks/tt100/truth/ex200.truth`](../../benchmarks/tt100/truth/ex200.truth),
with its upstream attribution and license documented in
[`benchmarks/tt100/README.md`](../../benchmarks/tt100/README.md).

## Recovery and rewriting

1. The truth-table recovery tool identifies BF16 exponential behavior and its
   finite-width numerical rules: subnormal inputs are treated as zero (DAZ),
   subnormal outputs are flushed to zero (FTZ), conversion uses round to nearest
   with ties to even (RNE), and NaNs produce the canonical encoding `16'h7fc0`.
2. `initial.v` decodes fields, uses fixed-point ln(2) range reduction and a
   degree-six Horner polynomial, and normalizes and rounds the output.
   RTL validity checks and independent complete-domain replay pass for all
   65,536 input words. Its syntax cost is Q = 32.
3. `rewritten.v` separates arithmetic evaluation from output selection and
   replaces nested procedural branches with conditional expressions.
   The arithmetic and finite-width behavior remain unchanged. Independent
   complete-domain replay again passes for all 65,536 input words, at Q = 24.

| Implementation | RTL validity | Complete-domain replay | Syntax cost Q |
| --- | --- | --- | ---: |
| `initial.v` | Pass | 65,536 / 65,536 | 32 |
| `rewritten.v` | Pass | 65,536 / 65,536 | 24 |

## Records and scoring

- `verification.json` extracts the original verification outcomes, complete
  input-domain coverage, source hashes, and checker identities from the archived
  experiment receipts. Machine-local paths and raw run logs are omitted.
- `costs.json` records costs and per-construct counts for both candidates.
- `scoring/` contains the frozen final TT-100 evaluator and weights. Their hashes
  match `experiments/tt100-final/metadata.json`. Use these files to reproduce
  the paper's costs, rather than the current toolkit's default cost profile.
- `SHA256.json` lists checksums for the files in this example package.

The final RTL hash and Q = 24 agree with the `ex200` record in
[`recovered_functions.csv`](../../experiments/tt100-final/recovered_functions.csv).
The archived verification outcomes above are historical measurements. Running
checks today produces new verification results without replacing those records.
No LLM generation is performed by the commands below.

## Recheck both implementations

Run from the repository root. Cost evaluation requires Python 3 only:

```bash
python3 examples/bf16-exp/scoring/RTL_cost_calculator.py examples/bf16-exp/initial.v examples/bf16-exp/rewritten.v --cost-csv examples/bf16-exp/scoring/syntax_cost.csv --json --detail
```

RTL validity and complete-domain equivalence checks require Yosys and Icarus
Verilog. Each command checks every input word and every output bit against the
original table, without reusing the verification cache:

```bash
python3 skills/circuit-reverse-rtl/scripts/verify_truth_yosys.py benchmarks/tt100/truth/ex200.truth examples/bf16-exp/initial.v --no-cache --json
python3 skills/circuit-reverse-rtl/scripts/verify_truth_yosys.py benchmarks/tt100/truth/ex200.truth examples/bf16-exp/rewritten.v --no-cache --json
```

The expected result for each implementation is `status: pass`, `frontend: pass`,
and `vectors: 65536`. Input bit order follows the official ABC `read_truth -xf`
convention described with the benchmark inputs.

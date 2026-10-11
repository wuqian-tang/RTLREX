# TT-100 original truth tables

This directory redistributes the 100 original truth tables `ex200.truth` through
`ex299.truth` from the official [IWLS 2026 contest repository](https://github.com/alanminko/iwls2026-ls-contest).
They are unchanged and match every input hash in the final RTLREX experiment
records in `experiments/tt100-final/input_manifest.json`.

- Source revision: `91ad493f4b7732fcbf5384c24c18baef3e07a0c2`.
- Original archive: [`benchmarks/iwls2026_truth_tables.tar.gz`](https://github.com/alanminko/iwls2026-ls-contest/blob/91ad493f4b7732fcbf5384c24c18baef3e07a0c2/benchmarks/iwls2026_truth_tables.tar.gz).
- Included inputs: `truth/ex200.truth` through `truth/ex299.truth`.
- Upstream copyright: Copyright (c) 2026 alanminko.
- License: the original [MIT License](LICENSE), preserved verbatim.
- `source.json` records the source revision, original archive checksum, license
  checksum, per-file hashes, and interface widths.

The format follows ABC `read_truth -xf`: each nonempty line describes one
output bit, and an unsigned input value `x` selects character `2**n - 1 - x`
from the left. The inputs contain no recovered RTL or function annotations.
RTLREX's recovered function descriptions and measurements are stored separately
in `experiments/tt100-final/`.

Run `python3 benchmarks/verify_inputs.py` from the repository root to verify all
100 files against the final measurement manifest and the source manifest.

# Release validation

The current distribution is `0.1.0-rc2`. Its clean-export validation is recorded
below. The September entries are historical, not a description of the current
file or test counts.

## Earlier 0.1.0-rc1 validation

The `0.1.0-rc1` preparation was checked on 2026-09-12 in a copy outside the
research workspace. **108 tests passed in 49.650 seconds, with no skipped
tests.** This includes strict ABC and SMT positive/negative examples, algebraic
and ROBDD checks, cofactor coverage, proof composition, executable discovery,
relative plan paths, and a standalone installation. Optimized Python is
rejected before verification can run with disabled assertions.

An additional native-sampler check found that unsupported ANSI headers could
produce empty output rows. The release now rejects missing supported outputs
and undriven output cones. Three focused tests passed in 3.079 seconds after
compiling the C++ source: all eight parity vectors, unsupported-header
rejection, and undriven-output rejection. The final total is **111 distinct
passing tests** across these two batches; the 108-test Python proof suite was
not represented as rerun after this separate C++ guard change.

The synthetic parity demo separately passed all three checks: strict equality,
rejection of the complemented output, and exhaustive replay of eight rows.
The truth-table recovery entry point also produced RTL passing exhaustive
replay. These are installation/regression results, not the paper's benchmark
results or an LLM ablation. No LLM API was called for these checks.

Local runtime: Python 3.10.12, Yosys 0.63+161 (`5fd39ff3e`), Berkeley ABC 1.01,
Z3 4.16.0. See [dependencies](DEPENDENCIES.md). GitHub Actions uses a separately
pinned OSS CAD Suite; current results are available in the repository's Actions tab.

The first remote CI runs passed the 111-test suite but exposed an Icarus version
difference in the demo: bare `$finish` printed an extra diagnostic line. The
truth-table testbench now uses `$finish(0)` while retaining exact output-row
counting. Four additional real-simulator regressions cover complete replay,
incorrect values, early termination, and unexpected extra output. All four
passed locally; the current suite contains 115 tests. This compatibility change
does not alter the archived paper verifier or its historical certificates.

Source changes relative to the research Skill are recorded in
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json). The original paper-bound
Skill and proof records were preserved. The export was checked for generated
binaries, private configuration, personal absolute paths and common credential
patterns. A clean pattern scan does not replace copyright/provenance review.

The complete-table update added exact ANF/ROBDD fallback certificates and a
faster in-simulator exhaustive replay. Six focused regressions passed, including
an asymmetric test for the ABC `read_truth -xf` input orientation and a candidate
whose input port is named `i`. In the 117-test local suite, 116 passed on the
first run; one algebraic-cone test exceeded its 10-second process budget and
passed immediately when rerun in isolation (four of four tests in that file).
The release-content audit then passed across 136 tracked and nonignored files.

## 0.1.0-rc2 preparation — 2026-11-07

On the Linux/Python 3.10.12 toolchain described above:

- 131 root tests and 151 Skill tests pass, without skips.
- All 200 TT-100 artifact/result joins and 183 terminal-file hashes match.
  The frozen final scorer reproduces all 183 recorded terminal costs.
- All 100 original truth-table inputs match their source/experiment manifests.
- All 30 PA-30 historical proof receipts match the frozen record, input and
  candidate identities. PA-30 published aggregates and package hashes match.
- Fresh cache-disabled equivalence checks pass for both conditions on `ex200`
  and `ex255`. This is a four-candidate export smoke check, not a rerun of the
  200 LLM experiments or a new validation claim for every terminal.
- The 136-file current portable Skill inventory is complete and hash-checked.
- The release-content pattern scan passes. Private transcripts, credentials,
  machine-local tool configuration and the compiled historical sampler are
  excluded. Historical RTL whitespace is intentionally preserved for hash identity.

The original September provenance file is preserved unchanged under
`docs/history/`. The current inventory records the portable package, while the
TT-100 archive independently checks its original evaluated Skill manifest.

A clean Git archive export also passes the dependency doctor, runnable demo,
release scan, source inventory, input checks, TT-100 result/artifact/cost checks,
and PA-30 result/receipt checks. Artifact inventory checking rejects unlisted
terminal files and evaluated Skill sources.

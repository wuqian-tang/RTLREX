# Release-candidate validation

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
Z3 4.16.0. See [dependencies](DEPENDENCIES.md). The prepared GitHub Actions
workflow uses a separately pinned OSS CAD Suite; remote CI has not yet run.

Source changes relative to the research Skill are recorded in
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json). The original paper-bound
Skill and proof records were preserved. The export was checked for generated
binaries, private configuration, personal absolute paths and common credential
patterns. A clean pattern scan does not replace copyright/provenance review.

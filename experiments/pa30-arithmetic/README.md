# PA-30 arithmetic synthesis and standard-cell mapping

This package contains the final, uniform synthesis comparison used in the RTLREX paper. Recovered high-level arithmetic exposes square symmetry and constant coefficients, enabling arithmetic lowering and Booth synthesis before standard-cell mapping. The original gate-level inputs are mapped directly. Both flows use the same Nangate45 typical library, a 2 ns ABC target, `BUF_X1` input driver, and 10 fF output load.

All 30 recovered designs complete synthesis, mapping, and timing analysis. The original `test22` reaches the 600 s synthesis/mapping limit. Arithmetic means use the same 29 completed pairs, without selecting a different profile for each case.

| Metric | Original gate-level input | Recovered arithmetic RTL | Change |
| --- | ---: | ---: | ---: |
| Mean standard-cell area (µm²) | 2738.387448275862 | 2690.479931034483 | −1.749479142243% |
| Mean maximum path delay (ns) | 1.498034931034483 | 1.452650000000000 | −3.029631024902% |

These are reductions in the paired arithmetic means. Individual circuits can trade area against delay. The comparison uses a single `timed_booth` profile for every recovered circuit and a single `timed_original` profile for every reference circuit.

## Check the results without EDA tools

```sh
python3 experiments/pa30-arithmetic/aggregate.py --verify-published
```

`data/measurements.csv` contains all 60 final measurements, including timeout statuses and unrounded values. `data/summary.json` records the shared case set, arithmetic means, changes, and win/equal/loss counts. The calculation is `100 × (recovered mean / original mean − 1)`, rather than an average of per-circuit percentage changes. `input_manifest.json` ties the results to input hashes and records the original recovery proof engines and proof-record hashes.

`sha256_manifest.json` covers every published package file except the manifest itself. The verification command checks these hashes as well as all result calculations. Published rule-regression records are in `data/arithmetic_rule_regression.json` and `data/cube_rule_regression.json`. The cube regression was added when preparing the portable package and covers 46 SAT-proved positive-cube instances and 23 unchanged signed-negative-exponent instances.

## What is included

- `rtl/`: the 30 unchanged recovered RTL artifacts whose original-to-recovery proofs were retained.
- `proof_records/`: field-selected historical receipts for all 30 proof routes. Source/candidate identities are checked against the frozen proof index and input manifest, and original record hashes are retained separately from exported receipt hashes. These receipts are not self-contained replay certificates. Original-derived AIGs, auxiliary netlist cones, raw logs and historical tool snapshots are not bundled. Their original syntax costs and recovery classifications are unchanged.
- `synthesis_json/`: the exact lowered logic used for synthesis, with source-location metadata removed and source-derived hidden cell/net names shortened for portability. These metadata and name changes alter file hashes, but preserve the logic, connections, widths, and synthesis operations. Tool tie-breaking can depend on names, so exported-file reruns need not be byte-identical to the archived netlists. Both archived and published JSON hashes are recorded separately.
- `arithmetic_lowering.py`: the generic pre-`alumacc` JSON transformation, identical to the measured implementation. It expands unsigned squares using symmetric partial products and constant multipliers using canonical signed digits, at the existing output width. It has no case-ID dispatch.
- `check_lowering.py`: bounded formal regression for the arithmetic rules.
- `normalization/test11.v` and its evidence record: a synthesis-only replacement of an unsigned eight-bit cube by explicitly sized square and cube products. All 256 active input values were checked. The original recovered RTL remains in `rtl/test11.v`.
- `run_experiment.py`: a portable runner for the two final profiles. Original benchmark inputs are included under `benchmarks/pa30/inputs/`; third-party tools/libraries are supplied separately.
- `prepare_inputs.py`: regenerates lowered JSON from the retained recovered RTL. Its generic unsigned-cube rule replaces `x ** 3` by a full-width square followed by a product, resolving the unsupported native power cell in `test11` without a case-ID branch. It preserves the recovered RTL files.
- `check_cube_normalization.py`: bounded SAT regression against explicitly sized cube products and a guard check that signed negative exponents remain unchanged.
- `data/provenance.json`: tool versions, measured executable hashes, library provenance, and the frozen raw archive manifest hash. The raw archive contains additional logs and exploratory profiles and is not bundled here.

Verify receipt identities without running EDA tools:

```sh
python3 experiments/pa30-arithmetic/check_proof_records.py
```

## Correctness scope

The retained recovered RTL has existing strict proofs against the original gate-level circuits. The synthesis-only lowering is supported by exact arithmetic identities and a bounded SAT miter regression covering **887 rewritten multiplier cells**, operand widths up to six bits, truncation, widening, coefficient position, and signedness. This regression proves all input assignments within those bounded rule instances. It is not a new full-netlist certificate for each lowered PA-30 JSON file. Yosys/ABC synthesis and mapping are trusted in this supplementary measurement. No new end-to-end equivalence proof is claimed for the mapped outputs.

Run the rule regression with a compatible Yosys:

```sh
python3 experiments/pa30-arithmetic/check_lowering.py --yosys yosys --output /tmp/rtlrex-pa30-rule-check
python3 experiments/pa30-arithmetic/check_cube_normalization.py --yosys yosys --output /tmp/rtlrex-pa30-cube-check
```

To apply the generic lowering independently, supply a Yosys JSON design containing native arithmetic cells before `alumacc`:

```sh
python3 experiments/pa30-arithmetic/arithmetic_lowering.py --help
```

To regenerate inputs, including the unsigned-cube normalization, use:

```sh
python3 experiments/pa30-arithmetic/prepare_inputs.py --yosys yosys --output /tmp/rtlrex-pa30-regenerated-inputs
```

The intermediate square has twice the unsigned operand width, so it is exact. The final product is reduced to the original output width, matching Verilog's result. The recorded 256-value validation in `normalization/test11.json` is for the archived RTL expression replacement, not a separate full-circuit certificate for newly regenerated JSON. Freshly generated files can differ in names and internal representation from the archived inputs. To measure them, pass both `--json-dir /tmp/rtlrex-pa30-regenerated-inputs` and `--input-manifest /tmp/rtlrex-pa30-regenerated-inputs/input_manifest.json` to the runner. Do not replace the frozen published measurements with these new measurements.

## Reproduce synthesis and mapping

All 30 original PA-30 gate inputs are included under `benchmarks/pa30/inputs/`,
arranged as `test01/top_primitive.v` through `test30/top_primitive.v`.
[Official sources, checksums and third-party data terms](../../benchmarks/pa30/README.md)
are documented in the benchmark directory. The runner checks their recorded SHA-256 hashes before using them. It does not regenerate RTL with an LLM or choose new candidate files.

Obtain the pinned public Nangate45 library and its license in a directory outside the source checkout:

```sh
python3 experiments/pa30-arithmetic/fetch_library.py --output /tmp/rtlrex-nangate45
```

Then run both profiles:

```sh
python3 experiments/pa30-arithmetic/run_experiment.py \
  --inputs-dir benchmarks/pa30/inputs \
  --liberty /tmp/rtlrex-nangate45/NangateOpenCellLibrary_typical_no_wireload.lib \
  --yosys /path/to/yosys --abc /path/to/abc --sta /path/to/sta \
  --output /tmp/rtlrex-pa30-measurement --jobs 4
python3 experiments/pa30-arithmetic/aggregate.py \
  --measurements /tmp/rtlrex-pa30-measurement/measurements.csv
```

The executable options also honor `YOSYS`, `ABC`, and `OPENSTA` (or `STA`), then search `PATH`. The measured Yosys is `0.63+161` with Git revision prefix `5fd39ff3e`, which supports `synth -booth`. ABC reports version 1.01, compiled March 18, 2026. OpenSTA is 2.0.17. Use the executable hashes in the provenance file for exact binary matching. The runner records the actual hashes and versions of supplied tools, so runs with different tool builds remain distinguishable.

The Liberty derivation disables its default wire-load model. STA uses ideal interconnect, a 10 ns virtual clock with zero external input/output delays, a `BUF_X1` driving cell with 0.05 ns driver input transitions, and 0.01 pF output loads. The maximum reported data arrival time is the tabulated path delay. Mapping has a 600 s limit per task and STA has a 60 s limit. This measures standard-cell synthesis and mapping, not placement and routing.

Use `--cases test01 --jobs 1` for a small smoke run. Use a fresh output directory for every run. The frozen published measurements are never overwritten by the runner.

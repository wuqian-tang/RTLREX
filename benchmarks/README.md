# Benchmark inputs and sources

| Benchmark | Inputs | Source and verification |
| --- | --- | --- |
| TT-100 | All 100 original `ex200.truth`–`ex299.truth` files are included in `tt100/truth/` | [Source, pinned revision, and original MIT license](tt100/README.md) |
| PA-30 | All 30 original primitive-gate netlists are included in `pa30/inputs/` | [Official source, third-party terms, and checksums](pa30/README.md) |

Verify all included TT-100 files without EDA tools or an LLM:

```sh
python3 benchmarks/verify_inputs.py
```

Verify both included benchmark suites:

```sh
python3 benchmarks/verify_inputs.py --pa30-dir benchmarks/pa30/inputs
```

The verifier compares the input files to the hashes used in the final experiment
records. It does not rerun recovery or prove candidate RTL equivalence.

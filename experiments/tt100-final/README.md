# Final TT-100 RTLREX and LLM agent baseline results

This directory contains the final TT-100 measurements used by the manuscript.
Both conditions use GPT-5.6 Sol with `xhigh` reasoning and a 600-second generation
budget per case. Both conditions use the same model, task instructions,
generic tools, syntax-cost calculator, and independent verifier. The LLM agent
baseline does not receive RTLREX's domain-specific recovery procedures and
tools, which are packaged as an Agent Skill. The package remains frozen during
the experiment. Machine-readable records retain the original condition keys:
`with_skill` denotes RTLREX and `no_skill` denotes the LLM agent baseline.

| Condition | Validated RTL, V | High-level RTL, H |
| --- | ---: | ---: |
| RTLREX | 100 / 100 | 80 / 100 |
| LLM agent baseline | 81 / 100 | 74 / 100 |

V requires exact functional equivalence and RTL validity checks. H additionally
requires independently reviewed word-level or field-level computation without
input-enumerating answer overrides. Boolean or lookup implementations may
qualify for V without qualifying for H. The LLM agent baseline candidates for `ex223`,
`ex227`, and `ex228` contain arithmetic computation with input-specific answer
corrections. They count toward V and the V cost comparison but do not count
toward H.

The final scoring uses one identical syntax-cost evaluator and weight table for
both conditions. Q is a weighted Verilog syntax cost, not model spending.

| Same-case comparison | Cases | RTLREX wins | Ties | RTLREX losses | Mean Q, RTLREX | Mean Q, baseline | Mean Q reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Both V | 81 | 66 | 14 | 1 | 53.8148 | 1253.7778 | 95.71% |
| Both H | 74 | 60 | 14 | 0 | 21.6622 | 31.4189 | 31.05% |

Mean reductions use `100 * (1 - mean(RTLREX) / mean(LLM agent baseline))` on the same
cases. They are not averages of per-case percentage reductions. `ex228` is the
one V-paired case with higher RTLREX syntax cost. The V mean is sensitive to the
large Boolean implementations in the comparison condition. The H comparison
reports the common high-level subset separately.

## Included records

- `case_results.csv`: 200 records, one for each case and condition, with V, H,
  final Q, elapsed generation time, recorded token usage, and input/candidate
  hashes. A blank `policy_compliant` means no terminal candidate was available
  for that representation review. Representation policy does not filter V.
- `recovered_functions.csv`: 100 final RTLREX cases with English and Chinese
  function summaries, packed interface widths, V/H, Q, full recognition
  descriptions, and final candidate/input hashes. All 100 satisfy V, with
  52 floating-point, 25 integer, and 3 fixed-point high-level implementations,
  plus 20 exact bit-level Boolean implementations. Function names summarize
  RTLREX recognition rather than official benchmark annotations. For refined
  candidates, descriptions originate from recognition records for the same
  truth table, while hashes and costs refer to the final selected RTL.
- `cost_pairs.csv`: all 81 common validated cases, final costs, comparison
  outcome from RTLREX's perspective, and membership in the common H subset.
- `summary.json`: aggregates recomputed from the case records.
- `metadata.json`: endpoint definitions, budgets, tool/scorer provenance hashes,
  and source-file hashes from the selected final manuscript snapshot.
- `input_manifest.json`: case names, interface widths, and truth-table hashes.
  The corresponding original truth tables are included separately in
  `benchmarks/tt100/truth/`, with source attribution and the upstream MIT license.
- `SHA256.json`: checksums of the files in this export.

## Running example

The [`ex200` BF16 exponential example](../../examples/bf16-exp/README.md) provides
the initial and rewritten RTL, verification results, and syntax costs Q = 32
and Q = 24. It includes the frozen final evaluator and weights, plus commands
for independently checking both implementations against the original truth table.
The final RTL hash and cost agree with this package's `ex200` measurement record.

## Verify the published arithmetic

Run from any working directory using Python 3, with no EDA tools or LLM:

```sh
python3 experiments/tt100-final/verify_results.py
```

The script checks file hashes, all 200 records, case/input pairing, V/H counts,
cost wins/ties/losses, means, generation durations, and recorded token totals.
It also checks the recovered-function inventory against final measurements
and the input manifest, including all interface widths and the 100/80 V/H
counts. These joins do not independently certify the descriptive function names.
It verifies the arithmetic of the published measurement records. It does not
rerun RTL equivalence checks or the original generation experiment.

Token records exist for 99 RTLREX trials and 50 LLM agent baseline trials. Missing
usage remains missing. Recorded token sums therefore cannot establish total
LLM spending for either condition. Summed generation durations are per-case
durations, including budget expirations, rather than total elapsed time under
parallel execution.

The data are byte-identical to the selected final per-case manuscript CSV.
The summary and metadata are compact exports from that snapshot. The frozen
metadata records the scope of the original measurement export; the subsequently
added original truth tables are stored separately in `benchmarks/tt100/`.
Reference answers, private logs, and credentials are not included.
This is an evaluation on the development corpus rather than a separate held-out
benchmark. Retained LLM agent baseline candidates are scored by the common final evaluator
without rerunning their generation. Updating this software release does not
change the frozen Skill manifest or relabel these historical executions.

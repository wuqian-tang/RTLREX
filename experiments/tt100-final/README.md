# Final TT-100 Skill-access results

This directory contains the final TT-100 measurements used by the manuscript.
Both conditions use GPT-5.6 Sol with `xhigh` reasoning and a 600-second generation
budget per case. CREAS receives the frozen CREAS Agent Skill. The comparison
condition receives the general tools, syntax-cost calculator, and common
verification tool without the Skill's recovery procedures.

| Condition | Validated RTL, V | High-level RTL, H |
| --- | ---: | ---: |
| CREAS | 100 / 100 | 80 / 100 |
| CREAS without Skill | 81 / 100 | 74 / 100 |

V requires exact functional equivalence and RTL validity checks. H additionally
requires independently reviewed word-level or field-level computation without
input-enumerating answer overrides. Boolean or lookup implementations may
qualify for V without qualifying for H. The no-Skill candidates for `ex223`,
`ex227`, and `ex228` contain arithmetic computation with input-specific answer
corrections. They count toward V and the V cost comparison but do not count
toward H.

The final scoring uses one identical syntax-cost evaluator and weight table for
both conditions. Q is a weighted Verilog syntax cost, not model spending.

| Same-case comparison | Cases | CREAS wins | Ties | CREAS losses | Mean Q, CREAS | Mean Q, without Skill | Mean Q reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Both V | 81 | 66 | 14 | 1 | 53.8148 | 1253.7778 | 95.71% |
| Both H | 74 | 60 | 14 | 0 | 21.6622 | 31.4189 | 31.05% |

Mean reductions use `100 * (1 - mean(CREAS) / mean(without Skill))` on the same
cases. They are not averages of per-case percentage reductions. `ex228` is the
one V-paired case with higher CREAS syntax cost. The V mean is sensitive to the
large Boolean implementations in the comparison condition. The H comparison
reports the common high-level subset separately.

## Included records

- `case_results.csv`: 200 records, one for each case and condition, with V, H,
  final Q, elapsed generation time, recorded token usage, and input/candidate
  hashes. A blank `policy_compliant` means no terminal candidate was available
  for that representation review. Representation policy does not filter V.
- `recovered_functions.csv`: 100 final CREAS cases with English and Chinese
  function summaries, packed interface widths, V/H, Q, full recognition
  descriptions, and final candidate/input hashes. All 100 satisfy V, with
  52 floating-point, 25 integer, and 3 fixed-point high-level implementations,
  plus 20 exact bit-level Boolean implementations. Function names summarize
  CREAS recognition rather than official benchmark annotations. For refined
  candidates, descriptions originate from recognition records for the same
  truth table, while hashes and costs refer to the final selected RTL.
- `cost_pairs.csv`: all 81 common validated cases, final costs, comparison
  outcome from CREAS's perspective, and membership in the common H subset.
- `summary.json`: aggregates recomputed from the case records.
- `metadata.json`: endpoint definitions, budgets, tool/scorer provenance hashes,
  and source-file hashes from the selected final manuscript snapshot.
- `input_manifest.json`: case names, interface widths, and truth-table hashes.
  The third-party truth-table contents are not included.
- `SHA256.json`: checksums of the files in this export.

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

Token records exist for 99 CREAS trials and 50 without-Skill trials. Missing
usage remains missing. Recorded token sums therefore cannot establish total
LLM spending for either condition. Summed generation durations are per-case
durations, including budget expirations, rather than total elapsed time under
parallel execution.

The data are byte-identical to the selected final per-case manuscript CSV.
The summary and metadata are compact exports from that snapshot. No third-party
truth tables, reference answers, private logs, or credentials are published.
This is an evaluation on the development corpus rather than a separate held-out
benchmark. Retained no-Skill candidates are scored by the common final evaluator
without rerunning their generation. Updating this software release does not
change the frozen Skill manifest or relabel these historical executions.

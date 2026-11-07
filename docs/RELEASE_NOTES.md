# Release notes

## PA-30 input addition — 2026-11-07 (after rc2)

- Include all 30 original primitive-gate netlists with exact experiment hashes.
- Update synthesis instructions and CI to use and verify the bundled inputs.
- Preserve upstream provenance and distinguish these third-party inputs from
  MIT-licensed project code. Public redistribution terms remain unconfirmed.
- Final measurements, recovered RTL and historical proof receipts are unchanged.

## 0.1.0-rc2 — 2026-11-07

This release prepares the software companion and final experiment artifacts
for public inspection. It does not change the paper's measurements or rerun
LLM recovery. The version refers to this software distribution, not to the
historical evaluated Skill.

- Include all 183 terminal TT-100 RTL files, 200 historical validation receipts,
  exact task prompts, selected final protocols, original generic helper sources,
  generation scorers, and the common final scorer.
- Preserve absent, rejected and inconclusive outcomes. Add integrity checks,
  full final-cost recomputation, and optional fresh RTL equivalence checks.
- Include 135 unchanged evaluated Skill files with an original 137-file manifest;
  explicitly omit machine-local tool configuration and the compiled sampler.
- Include PA-30 historical proof receipts and source/candidate identity checks.
  These are not complete historical proof replay bundles.
- Repair dependency diagnostics for configured simulator/compiler paths.
- Refresh the portable source inventory; preserve the earlier export inventory
  in `docs/history/` and add CI checks for current inventory integrity.

The same final cost calculator reproduces both conditions' published costs.
Generation-time calculators and the corresponding prompt text differed;
`experiments/tt100-final/protocol/` documents that distinction explicitly.

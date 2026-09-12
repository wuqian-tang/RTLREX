# Proof scope

The supported domain is two-state, deterministic combinational logic. Preserve
the source interface, including packed ranges, orientation, widths and
signedness. Sequential equivalence and four-state simulation equivalence are
outside this release's claim.

| Route | What a strict result establishes |
| --- | --- |
| ABC CEC | Equality of every paired output after checked RTL lowering |
| SMT | All-output assertion miter, with serialized assertion dependencies audited |
| Output SAT | Complete output-bit coverage; lemma routes use only previously proved equalities |
| Algebraic replay | Source-bound reduction and independent polynomial certificate replay |
| Native ROBDD | Exact zero residual coefficients evaluated from native gates, within an explicit node cap |
| Cofactor checking | Every assignment of the selected controls, with all remaining inputs free |
| Composition | Every declared lemma, interface bridge and residual output obligation |
| Complete-table replay | Every input assignment in the supplied complete truth table, preserving the ABC `read_truth -xf` complemented-index convention |
| Structural truth replay | Every ANF/ROBDD fallback signal evaluated over the complete domain and checked against every output row |

An output projection, coefficient identity, or individual AIG proof is a lemma.
It becomes a whole-circuit proof only after all original inputs and outputs are
bound through a complete, checked proof chain. A complete truth table permits
exhaustive replay; random vectors do not.

The optional ANF/ROBDD fallback establishes exact functionality for a complete
table, but it is a low-level Boolean representation. Its result must not be
reported as recovered word-level RTL or used to inflate a high-level recovery
metric.

Resource exhaustion, unsupported syntax and incomplete coverage remain
inconclusive. A simulation-only acceptance during exploration is explicitly
non-strict and must not be used to certify a final candidate. X/Z values and
undriven output fanins are rejected by the strict frontend guard.

The LLM proposes decomposition and intermediate RTL. The verifier checks those
proposals. The presence of deterministic matchers and reusable proof checkers
does not establish the LLM's separate causal contribution; that needs an
appropriate experimental comparison.

Some algebraic implementations use Python assertions as proof guards. Run
normal Python; optimized mode (`python -O` or `PYTHONOPTIMIZE`) is unsupported.

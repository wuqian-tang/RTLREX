# Reproducibility scope

This release makes the Skill instructions, deterministic tools and verification
regressions inspectable and executable. The included synthetic tests are not
benchmark results and are not an end-to-end LLM recovery evaluation.

The associated manuscript reports strict certification for all 30 retained
PA-30 candidates. Those results include later verification of retained
development outputs. Portability edits in this release do not turn those
historical runs into a new frozen-protocol experiment. The complete source-bound
proof archives and original benchmark inputs are not part of this repository.

To independently assess all paper numbers, a separate research artifact needs:

1. Legally redistributable inputs, or original download locations and hashes.
2. Exact retained RTL, source hashes, complete proof plans and certificates.
3. Fixed Skill commit, prompts, model identifier, configuration and budgets.
4. Per-run results and the scripts that generate every comparison table.
5. Clear distinctions between generation, fresh proof execution and archive replay.

Agent-guided recovery requires a separately configured LLM host. Its model,
context policy, runtime, token usage and randomness are not supplied by this
repository. Existing limitations in the manuscript concerning frozen generation
protocols, complete timing traces and separation of LLM/tool contributions are
not resolved merely by releasing code.

`examples/prompts/with_skill.txt` and `without_skill.txt` are **new illustrative
templates**, not historical paper prompts. Their task bodies are identical;
the first line changes Skill access. For a controlled experiment, configure
the same model, interface, limits and inputs externally, enforce the access
difference, and retain the actual rendered prompts and run traces. These
templates do not by themselves demonstrate a fair measured ablation.

For a public release, freeze a Git tag and commit, run the tests from a clean
checkout, and archive that exact tag with a persistent identifier. Reference
the version actually evaluated. Never replace a historic verifier hash with
the hash of a later implementation and describe the old execution as fresh.

The `.truth` reader uses one output bit per line and complemented input-index
order, matching ABC-style input. The parity example is documented in
`examples/parity/README.md`. Use the active allowed-syntax whitelist separately
from numerical syntax cost.

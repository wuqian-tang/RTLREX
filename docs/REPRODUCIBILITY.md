# Reproducibility scope

The release includes executable Skill tools, synthetic verification regressions,
and [final experiment artifacts](../experiments/README.md). The experiment
packages provide per-case data and scripts to check the reported aggregates.
The [original TT-100 inputs](../benchmarks/tt100/README.md) are included with
upstream attribution and the original MIT license.
[PA-30 input sources and checksums](../benchmarks/pa30/README.md) are documented
for separate acquisition. Reference answers, model credentials, and the
complete source-bound PA-30 proof archives are not bundled.

## PA-30 synthesis and mapping

[The PA-30 package](../experiments/pa30-arithmetic/README.md) evaluates all 30
retained recovered RTL implementations. A uniform arithmetic-aware flow uses
square symmetry, signed-digit constant multiplication, and Booth encoding.
Original gate-level netlists are mapped directly. Both sides use the same
Nangate45 typical-corner library and driving-cell, load, and mapping-delay
constraints. Area and delay always come from the same mapped implementation.

The reported paired means use the 29 circuits with completed measurements on
both sides. The original test22 mapping reaches the 600-second limit, while
the recovered implementation completes. Missing measurements are not zeros.
The chosen synthesis profile is shared across cases, rather than selected
separately to obtain each case's best area or delay.

The retained original-to-recovered proofs and the arithmetic-lowering checks
are separate evidence. Generic lowering is based on exact bit-vector
identities and has bounded formal regression coverage of 887 rewritten
multiplier instances. These checks do
not constitute a new full-circuit equivalence certificate for every lowered
JSON design. Native Yosys/ABC synthesis and mapping are trusted in this study.
The package records this distinction, source hashes, library provenance,
and measured tool versions. A portable rerun records its own tool identity
rather than replacing the historical record.

## TT-100 recovery and cost comparison

[The TT-100 package](../experiments/tt100-final/README.md) contains the final
per-case results and the common-case comparisons. Validated RTL satisfies
complete-domain equivalence and RTL validity checks. The high-level subset
also satisfies the separately audited representation criterion. Input-specific
output corrections are annotated and count toward validation, but not toward
the high-level subset.

All terminal candidates use the same final syntax-cost evaluator and weights.
Paired means compare the same cases, with unresolved or missing candidates
excluded from numerical pairs but retained in the 100-case coverage counts.
Recorded token usage is incomplete and does not establish a total LLM bill.
Recomputing aggregate data is different from regenerating the agent runs.
Generation requires a separately configured LLM host and the archived model,
prompts, Skill version, budgets, and inputs described in the package metadata.

The [BF16 running example](../examples/bf16-exp/README.md) additionally provides
two original experiment RTL candidates, archived verification outcomes, and the
frozen TT-100 scoring files. Its commands recompute costs or independently recheck
complete-domain equivalence without regenerating an LLM recovery run.

## Software and prompts

Synthetic tests check tool behavior, negative controls, and portability. They
are not new benchmark recovery runs. Current installation and portability
changes do not replace the hashes of the Skill and tools evaluated in the
archived experiments.

`examples/prompts/with_skill.txt` and `without_skill.txt` are illustrative
templates. [Historical paper prompts](paper-prompts/README.md) are labeled
separately. A controlled recovery comparison must keep the same model,
interface, budgets, and inputs, enforce the Skill-access difference, and retain
the actual prompts and traces.

The `.truth` reader uses one output bit per nonempty line and complemented
input-index order, matching ABC `read_truth -xf`. See the synthetic parity
example in `examples/parity/README.md`. Numerical syntax cost and an allowed
syntax whitelist are separate checks.

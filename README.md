# RTLREX

RTLREX is an LLM-guided framework for exact high-level RTL recovery from
combinational gate-level netlists or complete truth tables. An LLM plans recovery and refinement using domain-specific procedures
and tools for probing, recognition, RTL generation, and rewriting. Independent
verification checks candidates against the original input before acceptance.

The domain-specific procedures and tools are packaged as **one Agent Skill**,
`circuit-reverse-rtl`. This repository is the software companion to the RTLREX
paper. **RTLREX** names the framework and repository;
`circuit-reverse-rtl` remains the installable Skill identifier and invocation
name. The package does not contain a model or require an API key to run its
checkers and tests.

## What is included

- Word-level recovery and syntax-cost tools, including truth-table recognition,
  plus an opt-in exact low-level Boolean fallback for unmatched complete tables.
- Budgeted complete-truth-table recovery with verified checkpoints, atomic
  promotion of lower-cost candidates, and bounded refinement.
- Strict ABC/SMT checking, independent algebraic replay, native ROBDD coefficient
  checking, complete cofactor coverage, and checked proof composition.
- Synthetic examples, negative controls, an installer, and portable tests.
- [BF16 exponential running example](examples/bf16-exp/README.md), with the
  actual initial and rewritten RTL, verification records, and frozen scoring files.
- Agent instructions and references describing proof obligations and boundaries.
- [Representative historical paper prompts](docs/paper-prompts/README.md), with
  source mapping and a clear distinction from illustrative examples.
- [Final experiment artifacts](experiments/README.md), including PA-30
  arithmetic-aware synthesis and mapping measurements and TT-100 paired costs.

For netlists, the agent discovers useful hypotheses, intermediate words and proof
plans. The complete-truth-table tool recognizes supported arithmetic families
and verifies its emitted RTL. These tools do not guarantee that every circuit can be recovered or
proved within a fixed budget. See [proof scope](docs/PROOF_SCOPE.md).

## Quick start

Use Linux with Python 3.10 or later. Install Yosys, Berkeley ABC, Icarus Verilog,
Z3 and a C++17 compiler. See [dependencies](docs/DEPENDENCIES.md) for versions and
tool configuration. NumPy is used by some truth-table recognition paths:

```bash
git clone https://github.com/wuqian-tang/RTLREX.git
cd RTLREX
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 scripts/doctor.py --require-all
python3 scripts/demo.py --out outputs/parity-demo
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The demo strictly proves a synthetic three-input parity circuit, rejects an
intentionally incorrect implementation, and exhaustively replays all eight
truth-table rows. It makes **zero LLM calls**. Use a new `--out` directory when
running it again.

To use the Skill with Codex, copy it to a new local skill directory:

```bash
python3 scripts/install.py --dest "$HOME/.agents/skills/circuit-reverse-rtl"
```

The installer refuses to overwrite an existing installation. Other Agent Skill
hosts can use the same folder at their supported skill location. See
[Codex's local skill discovery documentation](https://learn.chatgpt.com/docs/build-skills).

Example agent request:

```text
Use $circuit-reverse-rtl to recover high-level combinational RTL from input.v.
Preserve every input and output, their ranges and signedness. Put candidates
and logs in outputs/recovery/. Prove exact equivalence before promoting final.v.
If proof is inconclusive, report it as inconclusive and retain the evidence.
```

## Standalone verification

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v --strict-cec --json
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v --engine smt --json
python3 skills/circuit-reverse-rtl/scripts/verify_truth_sim.py function.truth candidate.v --json
python3 skills/circuit-reverse-rtl/scripts/recover_truth.py function.truth outputs/final.v --budget-seconds 240 --json --brief
python3 skills/circuit-reverse-rtl/scripts/truth_reverse.py function.truth --out-dir outputs/truth --allow-boolean-fallback --verify --json
python3 skills/circuit-reverse-rtl/scripts/verify_truth_structural.py function.truth structural.v --certificate certificate.json --json
```

Always inspect the structured status. Random simulation without a
counterexample is not a strict proof. Exhaustive replay of every row in a
complete truth table is exact for that table. The structural fallback is
reported separately from recovered word-level RTL. Supported algebraic and
composed routes are documented in
[the exact CEC reference](skills/circuit-reverse-rtl/references/exact_cec.md).

## Cost and benchmark data

The default CSV is a **custom truth-table study profile**, derived from the
ICCAD 2022 Problem A syntax-cost specification. The calculator is this project's
implementation, not an official contest parser. Syntax cost is distinct from
mapped area, delay and power. Supply your own `--cost-csv` when a different
profile is required. [Source attribution](NOTICE.md) and
[reproduction scope](docs/REPRODUCIBILITY.md) explain the distinctions.

The experiment packages include per-case measurements, aggregation scripts,
and instructions for the published synthesis study. They distinguish measured
data, retained recovery proofs, and regression checks of arithmetic lowering.
The [100 original TT-100 truth tables](benchmarks/tt100/README.md) are included
with their original MIT license and source attribution.
[PA-30 source links and input checksums](benchmarks/pa30/README.md) are provided
for separately obtaining its original netlists. Reference answers, paper PDFs
and full PA-30 proof archives are not bundled. Replaying the synthesis study requires separately obtained inputs,
the specified standard-cell library and EDA tools. Regenerating LLM recovery
runs also requires an independently configured model host.

## Citation and license

This repository accompanies *RTLREX: LLM-Guided Framework for
Exact High-Level RTL Recovery*. Software citation metadata is in
[CITATION.cff](CITATION.cff). A paper DOI/arXiv identifier will be added when one
exists.

The project code and documentation are licensed under the [MIT License](LICENSE).
Academic and commercial use, modification and redistribution are permitted
provided the copyright and permission notices are retained. External tools and
data retain their own terms; see [NOTICE.md](NOTICE.md).

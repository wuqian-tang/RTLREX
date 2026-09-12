# Circuit Reverse RTL

A domain-specific Agent Skill for recovering high-level RTL from combinational
gate netlists and complete truth tables. An LLM proposes hypotheses and proof
plans; external tools check the recovered implementation against the input.

This repository contains **one Skill**, `circuit-reverse-rtl`, with reusable
probing, recovery, rewriting, and exact-equivalence tools. It is the software
companion being prepared for *LLM-Guided Circuit Reverse Engineering with an
Agent Skill*. The package does not contain a model or require an API key to run
its checkers and tests.

## What is included

- Word-level recovery and syntax-cost tools, including truth-table recognition.
- Strict ABC/SMT checking, independent algebraic replay, native ROBDD coefficient
  checking, complete cofactor coverage, and checked proof composition.
- Synthetic examples, negative controls, an installer, and portable tests.
- Agent instructions and references describing proof obligations and boundaries.
- [Representative historical paper prompts](docs/paper-prompts/README.md), with
  source mapping and a clear distinction from illustrative examples.

The agent still has to discover useful hypotheses, intermediate words and proof
plans. These checkers do not guarantee that every circuit can be recovered or
proved within a fixed budget. See [proof scope](docs/PROOF_SCOPE.md).

## Quick start

Use Linux with Python 3.10 or later. Install Yosys, Berkeley ABC, Icarus Verilog,
Z3 and a C++17 compiler. See [dependencies](docs/DEPENDENCIES.md) for versions and
tool configuration. NumPy is used by some truth-table recognition paths:

```bash
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
```

Always inspect the structured status. Simulation without a counterexample is
not a strict proof. Supported algebraic and composed routes are documented in
[the exact CEC reference](skills/circuit-reverse-rtl/references/exact_cec.md).

## Cost and benchmark data

The default CSV is a **custom truth-table study profile**, derived from the
ICCAD 2022 Problem A syntax-cost specification. The calculator is this project's
implementation, not an official contest parser. Syntax cost is distinct from
mapped area, delay and power. Supply your own `--cost-csv` when a different
profile is required. [Source attribution](NOTICE.md) and
[reproduction scope](docs/REPRODUCIBILITY.md) explain the distinctions.

Contest benchmarks, reference answers, paper PDFs, full experimental logs and
full PA-30 proof archives are not bundled. The included examples are synthetic.
This software release alone does not reproduce the paper's complete tables.

## Citation and license

Software citation metadata is in [CITATION.cff](CITATION.cff). A paper DOI/arXiv
identifier will be added when one exists.

The project code and documentation are licensed under the [MIT License](LICENSE).
Academic and commercial use, modification and redistribution are permitted
provided the copyright and permission notices are retained. External tools and
data retain their own terms; see [NOTICE.md](NOTICE.md).

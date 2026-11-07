# RTLREX

RTLREX is an LLM-guided framework for exact high-level RTL recovery from
combinational gate-level netlists or complete truth tables. An LLM coordinates
function recovery, RTL generation, and cost-guided rewriting using domain-specific
tools. Independent verification checks candidates against the original input.

The tools and procedures are packaged as an Agent Skill named
`circuit-reverse-rtl`. Recovery with an LLM requires a separately configured
model host. Standalone tools and tests run without an LLM or API key.

## What is included

- Function-recovery, RTL-generation, and syntax-cost tools, with verified
  checkpoints and cost-guided refinement.
- Equivalence checking through ABC, SMT, arithmetic proofs, and complete
  truth-table validation. See [supported proof routes](docs/PROOF_SCOPE.md).
- Agent instructions, an installer, examples, and verification tests.
- [BF16 exponential example](examples/bf16-exp/README.md), including initial
  and rewritten RTL, verification records, and scoring files.
- [Paper experiment artifacts](experiments/README.md), including final RTL,
  measurements, verification records, task prompts, and analysis scripts.

For netlists, the agent proposes functions, intermediate RTL, and proof plans.
For complete truth tables, the recovery tool matches supported function models
and verifies the generated RTL. An optional Boolean fallback produces an exact
low-level implementation when no supported model matches. Recovery and proof
completion depend on the input and available resources.

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

The demo checks a three-input parity circuit and rejects an incorrect
implementation, without calling an LLM. Use a new `--out` directory for each run.

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

## Standalone tools

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v --strict-cec --json
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v --engine smt --json
python3 skills/circuit-reverse-rtl/scripts/verify_truth_sim.py function.truth candidate.v --json
python3 skills/circuit-reverse-rtl/scripts/recover_truth.py function.truth outputs/final.v --budget-seconds 240 --json --brief
python3 skills/circuit-reverse-rtl/scripts/truth_reverse.py function.truth --out-dir outputs/truth --allow-boolean-fallback --verify --json
python3 skills/circuit-reverse-rtl/scripts/verify_truth_structural.py function.truth structural.v --certificate certificate.json --json
```

Inspect each tool's returned status: passing sampled simulations alone does
not establish equivalence. Matching every output for every input in a complete
truth table establishes equivalence for that table. Boolean fallback results
are distinct from recovered word-level RTL.
See the [verification reference](skills/circuit-reverse-rtl/references/exact_cec.md)
for detailed proof requirements.

## Cost and benchmark data

The default syntax-cost weights extend the ICCAD 2022 Problem A specification
for the truth-table study. The calculator is a project implementation, not the
official contest parser. Syntax cost is distinct from mapped area, delay, and
power. Use `--cost-csv` to select different weights.

- [TT-100](experiments/tt100-final/README.md): final candidates, validation
  records, and scripts for checking costs and reported results. The
  [experiment protocol](experiments/tt100-final/protocol/README.md) provides
  the task prompts, evaluated Skill snapshot, and scoring tools.
- [PA-30](experiments/pa30-arithmetic/README.md): recovered RTL, synthesis and
  mapping measurements, and historical recovery proof records. Complete
  historical recovery-proof replay bundles are not included.
- [TT-100 inputs](benchmarks/tt100/README.md): all 100 original truth tables,
  with their upstream MIT license and attribution.
- [PA-30 inputs](benchmarks/pa30/README.md): all 30 original netlists, with
  source links and checksums. These are third-party data, outside the project's
  MIT license; public redistribution terms remain unconfirmed.

Rerunning synthesis requires the specified EDA tools and standard-cell library.
Regenerating recovery runs additionally requires an LLM host. See
[reproduction scope](docs/REPRODUCIBILITY.md) for instructions and the distinction
between the current software and the code used in the experiments. Software
changes are documented in the [release notes](docs/RELEASE_NOTES.md).

## Citation and license

This repository accompanies *RTLREX: LLM-Guided Framework for Exact High-Level
RTL Recovery*. Software citation metadata is provided in
[CITATION.cff](CITATION.cff). The paper's arXiv identifier will be added upon
announcement.

The project code and documentation are licensed under the [MIT License](LICENSE).
Academic and commercial use, modification and redistribution are permitted
provided the copyright and permission notices are retained. External tools and
data retain their own terms; see [NOTICE.md](NOTICE.md).

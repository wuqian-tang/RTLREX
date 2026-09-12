---
name: circuit-reverse-rtl
description: Reverse-engineer combinational circuits from truth tables, AIG-style cases, or primitive-gate Verilog into compact word-level RTL; validate by simulation/CEC and minimize RTL cost.
---

# Circuit Reverse RTL

Use this skill when asked to infer the behavior of a combinational circuit and produce a compact, equivalent `module top` RTL implementation. The source can be a truth table, an AIG-style artifact, a flattened primitive-gate Verilog netlist, or a repository-specific benchmark format.

## Operating Model

- Preserve the complete source interface contract: top module name when required,
  ordered port names and directions, exact packed left/right ranges (including
  bit orientation), widths, and signedness.  A width-only match is insufficient.
- Treat correctness as the gate. Do not promote a candidate after an explicit CEC `fail`, simulation mismatch, or counterexample. During RTL exploration, `cec.py --engine auto` results that report `pass (non-strict)` may be used as a fast working equivalence signal: ABC was inconclusive but random simulation passed with no observed mismatch. Report that this is not a strict proof. Before promoting a final RTL Verilog, require strict equivalence: first try the existing strict CEC flow; if it only reaches `pass (non-strict)`, use an exact backend described below, such as all-output SMT, independently replayed algebraic reduction, complete output-bit SAT, or a checked composition plan.
- Prefer word-level structure over gate-level fallback: arithmetic, comparisons, muxes, reductions, encoders/decoders, polynomial or affine forms, interval logic, and piecewise formulas.
- For a complete truth table, an explicit `--allow-boolean-fallback` may be used after semantic recognition fails. It emits the smaller of a shared ANF network and a shared ROBDD network, marks the candidate as low-level, and verifies every input assignment by an independent structural replay. This closes exact functional coverage without counting the result as recovered word-level RTL.
- Do not hard-code benchmark answers, case names, golden-derived formulas, or unique port-shape dispatch tables. Use references or golden outputs only to identify general algorithm gaps, then implement reusable learners or rewriting passes that validate against the source netlist.
- Do not emit truth-derived lookup tables or `case` enumerations by default. Prefer a reusable formula or algorithmic implementation whose constants follow from the inferred semantic contract. Use a table only when the user explicitly permits it.
- Keep the implementation combinational and deterministic. Avoid latches, clocks, delays, non-synthesizable constructs, and random behavior.
- Use local tools when present. This skill bundles scripts under `scripts/` for samplers, reversers, CEC wrappers, cost calculators, probing helpers, and GF(2) solvers. External engines are separate dependencies. Executable flags override `YOSYS`, `ABC`, `YOSYS_SMTBMC`, `IVERILOG`, `VVP`, and `CXX` environment variables, then PATH discovery. The CEC wrapper also accepts an optional legacy `--tool-config`; no configuration file or research checkout is required. For strict arithmetic CEC, `cec.py` can use Yosys SMT2 with an SMT solver, independently replayed polynomial reduction, or output-bit SAT within their documented support boundaries.
- Minimize after correctness. Use the local cost model or synthesis metrics that match the user's target.
- After equivalence, treat the benchmark cost as the primary optimization objective. Human readability and compactness are secondary objectives: improve them when cost is unchanged or only after the lower-cost candidate is secured.
- Keep reverse generation and cost-aware selection separate. First reverse as much gate-level structure as possible into behavioral RTL; then run cost-aware rewriting/post-processing with the active benchmark CSV. A correct but higher-cost candidate can be rejected by the post-processing step in favor of a cheaper fallback, but that decision should not live inside the datapath reverser.
- When declarations do not affect cost, merge compatible input/output/wire declarations and remove duplicate redeclarations to make the final RTL shorter and easier to read.
- For repeated operators that the cost model charges textually, consider helper functions or submodules only when the target syntax allows them and the cost model rewards them. Validate carefully because helper argument widths and signedness can change behavior.
- Treat an allowed-syntax file as a hard whitelist, not merely a cost table. Before promoting or comparing cost, run `check_allowed_syntax.py`; a low-cost equivalent candidate that uses absent keywords such as `function/endfunction` is invalid and must be rejected. The cost calculator assigning it a number does not make the syntax legal.
- For negative constants, an equivalent signed based literal can avoid charging a unary `-` in some cost models. Use it only when it preserves signed comparison/arithmetic semantics and validation passes.
- When continuing an already partially reversed RTL, prioritize replacing remaining gate-level primitive cones with word-level behavior before doing surface-level high-level rewrites for cost. Treat syntax-only cost reductions, such as removing redundant casts or concats, as a later cleanup step after gate-level structure has been exhausted or blocked.
- Once all primitive-gate output cones are fully explained and verified, switch to RTL rewriting: remove dead scaffolding, simplify expression width/sign-extension, share repeated terms, and revalidate each cost-reduction step.

## Tool Discovery

Locate this `SKILL.md` and use its sibling `scripts/` directory. Examples below
use the source-checkout path `skills/circuit-reverse-rtl/scripts`; when installed
elsewhere, replace that prefix with the installed Skill's script directory.
Module invocations need that directory in `PYTHONPATH`; direct wrapper scripts
locate their own package automatically. Work files are relative to the invoking
working directory, independently of where the Skill is installed.

Check the tools needed by the route you choose:

```bash
command -v yosys
command -v abc || command -v yosys-abc || command -v berkeley-abc
command -v yosys-smtbmc
command -v z3
command -v iverilog
command -v vvp
```

Set executable paths with the environment variables above if they are absent
from PATH. Explicit flags are supported on the verifiers that expose them;
nested checks inherit the environment. Invalid explicit or configured paths
fail without silently selecting another binary. The fast sampler builds from
its C++ source using `CXX` or `g++`/`clang++`, caching in the working directory.
No prebuilt sampler, solver, contest benchmark, or research proof is bundled.
Verification refuses optimized Python (`-O`, `-OO`, or `PYTHONOPTIMIZE`), so
assertion-based invariants cannot silently disappear.

JSON proof plans resolve relative `{path, sha256}` artifact records against the
plan file's directory. Local-identity `source_path` is relative to its identity
file. Certificate APIs accept `base_dir` for relative input/candidate and
certificate file names, defaulting to the invocation directory. Hash checks and
all proof duties still apply after resolution. Generated records retain resolved
paths; moving an archive requires updating path fields and any containing hashes.
These source changes form a release version distinct from the frozen research
checker; original research certificates are not claimed to certify this version.

Common tool categories:

- Verification: CEC wrappers, exhaustive truth-table checkers, random simulation harnesses.
- Sampling: primitive-netlist evaluators, truth-table readers, AIG simulators, cached random-vector probes.
- Reversal: datapath template generators, affine/polynomial learners, structural recognizers, GF(2) Gaussian-elimination helpers.
- Cost: contest cost calculators, gate counters, synthesis reports.
- External engines: Yosys, ABC, iverilog/vvp, SAT/SMT tools, synthesis scripts.

## Reference Navigation

Keep this file as the core workflow. Load the focused references only when the task needs that level of detail:

- `references/gate_level_probing.md`: use for primitive-gate Verilog, internal signal sampling, cone tracing, branch probing, and bus matching.
- `references/algebraic_fitting.md`: use for GF(2), ANF, Gaussian-elimination coefficient solving, and modular arithmetic fitting.
- `references/rtl_rewriting.md`: use after gate-level cones are fully reversed and the remaining task is lowering RTL cost without changing behavior.
- `references/exact_cec.md`: use when whole-circuit ABC/SMT is inconclusive, to localize output-bit obligations and evaluate sound decomposition routes.
- `references/aig_cases.md`: complete primary-input cofactor proofs and independently audited archive replay for full AIG pairs; original RTL bridges remain mandatory.

## Workflow

1. Identify the interface.
   - Parse inputs, outputs, widths, signedness clues, and packing conventions.
   - Classify outputs as words, flags, predicates, packed fields, or mixed bundles.
   - For truth tables or AIGs, confirm bit order and input orientation before fitting formulas.

2. Build a reliable oracle.
   - For primitive Verilog, simulate or sample the original netlist.
   - For truth tables, use exhaustive lookup when feasible.
   - For AIGs, use the repository's simulator or synthesis/CEC scripts.
   - Cache sampled values for repeated hypothesis testing, then refresh with independent samples before trusting a learned model.

3. Decompose the behavior.
   - For truth tables, first produce a high-level textual description before writing RTL. Match the table against reusable semantic models such as integer arithmetic, BF16/FP16 unary math (`sqrt`, `sin`, `tan`, `exp`, `log`, reciprocal families), format conversion, permutation, or affine/bit-level structure. Record the exact format assumptions, rounding, DAZ/FTZ, NaN, saturation, and exceptional-value behavior that were matched. For floating-point functions, implement field decode, range reduction, fixed-point polynomial/iterative evaluation, normalization, and rounding structurally; validate the complete truth table.
   - Try structural arithmetic first: add/sub/mul, shifts, comparisons, min/max, saturation, muxes, popcount, reductions, encoders, and priority logic.
   - For partially reversed primitive netlists, focus first on the still-primitive cones that feed outputs or already identified word-level intermediates. Infer and replace these gate-level cones before polishing existing high-level RTL expressions for cost.
   - Separate data path from control. Probe controls as all-off, one-hot, paired, and random combinations.
   - For piecewise logic, identify guards first, then learn each branch with fixed controls.
   - For Boolean or small-output functions, expand monomials by degree and solve coefficients over GF(2) with Gaussian elimination. Validate on fresh samples because low-degree fits can overfit sparse probes.
   - For arithmetic coefficients, solve linear systems over the appropriate modular ring or field when the operation wraps. Track whether the modulus is `2^n`, an odd prime, or a mixed-width truncation.
   - For lookup-like behavior, prefer compact generated `case`, interval, or table structures only when they are cheaper and clearer than gates.

4. Generate a candidate.
   - Emit clean `module top` RTL with explicit intermediate widths.
   - Declare signed intermediates when signed shifts, products, or comparisons are intended.
   - Slice or extend deliberately; Verilog expression sizing is part of the function.
   - Keep exploratory files in a temporary or clearly named output area until verification passes.

5. Validate.
   - First run fast simulation or cached-sample checks to catch obvious errors.
   - A complete truth table supports exact exhaustive verification. The bundled replay preserves the complemented input-index convention of ABC `read_truth -xf`; do not compare a Verilog input directly with the raw character position. For the restricted ANF/ROBDD fallback grammar, `verify_truth_structural.py` evaluates every signal over the full input domain and emits a hash-bound certificate without relying on RTL simulation.
   - During exploration, use `cec.py --engine auto` as the normal fast checker. It may promote ABC `unknown/timeout` to `pass (non-strict)` only when random simulation also passes with no observed mismatch. This is acceptable for iterative RTL search, but it is not a formal proof.
   - For a final RTL Verilog candidate, require strict equivalence. First run the existing strict CEC path. If the result is already `pass`, promote it. If the result is `pass (non-strict)`, continue with an exact route: try all-output SMT first when the RTL preserves useful arithmetic, then use the supported algebraic, output-bit SAT, or checked-composition routes below. A timeout or partial proof remains inconclusive.
   - In `auto`, all three ABC engines (`&cec`, `dcec`, and `cec`) are allowed to finish.  A pass plus only unknown/timeout results remains a pass; any conclusive pass/fail disagreement is `conflict` and must not be promoted.  A watchdog timeout, cancellation, or abnormal nonzero exit dominates any partial success text already printed by a killed process.
   - The SMT backend builds an all-output assertion miter in Yosys, lowers generalized `$check` cells with `chformal -lower`, emits SMT-LIB2 with `write_smt2 -wires`, and runs `yosys-smtbmc -s z3 -t 1`. The lowering step is mandatory with newer Yosys versions; without it, `write_smt2` can omit immediate assertions and produce false-positive `PASSED` results. Before accepting the solver result, the checker audits the serialized model for every paired output equality, their aggregate, the assertion enable, every individual `miter_a N`, and the aggregate `miter_a` references. Missing or disconnected dependencies fail closed. This path preserves candidate arithmetic such as `bvmul`, but the reference can remain Boolean logic; word-level serialization alone does not make a hard multiplier proof tractable.
   - If whole-circuit proof is inconclusive, `cec.py --engine sat-bits` independently proves each output bit with Yosys SAT and records complete coverage in `coverage.json` when `--keep-tmp` is set. All bits must pass; partial coverage is inconclusive. No previously proved bit is assumed, and no internal cutpoint is introduced. Use `--sat-bit-timeout` and `--sat-total-timeout` to bound this stage.
   - If independent output bits stall in an arithmetic cone, try `cec.py --engine sat-lemmas`. It proves bits in order and allows a query to use only earlier equalities already proved in the same chain. Any non-pass result stops the chain, and only complete coverage is strict equivalence.
   - For primitive-gate references and unsigned arithmetic RTL within the supported subset, try `cec.py --engine algebraic`, or add `--algebraic-fallback` to `--engine auto --strict-cec`. This route proves local half- and full-adder identities by exhaustive evaluation of their small cuts, eliminates the original gate equations modulo each output width, and independently replays the proof against the candidate's word-level polynomial. For a difficult named arithmetic output, add `--algebraic-sliced-output <name>` so the checker reduces the reference-minus-candidate goal by output significance; the candidate polynomial is a proof target, never an input constraint. Small two-state comparison/reduction cells may control muxes after exhaustive truth-table lowering. If a few control bits cause polynomial blowup, repeat `--algebraic-case-split-bit '<port[bit]>'`; the checker must prove every Boolean assignment, every output must be sliced, and all unsplit primary inputs remain free. It returns `pass` only after all output words and all branches are proved. For cones with small original primary-input support, `--engine algebraic-cones` performs complete truth-table polynomial extraction and independent full-output replay; this separate route accepts neither case splits nor sliced-output options. A separate signed arithmetic path permits exact sign extension only after a native-width interval bound proves that no relevant overflow is lost. Unsupported shifts/truncations or mixed signedness, incomplete case coverage, nonmatching polynomials, or resource limits remain inconclusive; see `references/exact_cec.md`.
   - If long native Boolean functions prevent polynomial elimination, `--engine algebraic-terminal --algebraic-coefficient-input <port>` can retain them and discharge every residual coefficient by strict ABC after independent replay. Alternatively, `--algebraic-coefficient-engine bdd` evaluates original native gates directly with exact ROBDDs; set an explicit `--algebraic-bdd-node-cap` for larger obligations. Neither backend may assume a coefficient is zero. Its current scope is one complete output word, without case splits. For multi-stage proofs, `verify/composition.py` checks explicit taps, word stages, original-RTL bridges, and every residual output; `verify/chain.py` checks every adjacent pair of hash-bound intermediate RTLs. `verify/normalize_final_adder.py` constructs an explicit affine-plan compressor/ripple proposal and certifies the complete original-to-rewritten bridge. `verify/embedded_word.py` checks complete wider-word embeddings, exact original-output connections, and the retained candidate bridge for truncated arithmetic. `verify/grouped_algebraic.py` validates explicit outer cofactor groups and freshly replays every inner case; `verify/typed_product.py` certifies complete low-prefix product identities across native widths. These are reusable checkers; discovery of plans and intermediate hypotheses is still guided by the agent. Read `references/exact_cec.md` for schemas and support boundaries.
   - Do not repeatedly extend ABC timeouts after ABC is inconclusive. Switch to SMT for arithmetic-heavy final proof, or use cutpoint/bitwise decomposition if direct SMT also times out. Never accept an explicit `fail` or simulation mismatch.
   - On mismatch, inspect the first failing vector and test bit order, complementing, signedness, truncation, extension, constants, and guard priority.
   - If a Python model matches but RTL fails, debug expression widths by exposing candidate internals in a temporary testbench.

6. Evaluate and promote.
   - When the benchmark provides an allowed-syntax file, audit the candidate before interpreting its cost. Record rejected syntax experiments in candidate history, but never promote them or claim their cost as an improvement.
   - Measure cost with the local metric that matches the benchmark.
   - Prefer the lowest verified cost over a more readable but higher-cost form, unless the user has explicitly set a different tradeoff.
   - If primitive gates remain in output cones, continue gate-level reversal before doing cosmetic RTL cost cleanup unless blocked.
   - If all gate-level cones are replaced and verified, run RTL cleanup/rewrite passes and validate after each rewrite class. For equal-cost candidates, prefer the one with cleaner grouped declarations, fewer redundant wires, and simpler repeated structure.
   - Compare against primitive cost, previous candidate cost, or a user-provided target.
   - Promote only the verified candidate to the requested final location.
   - Do not overwrite user-retained RTL or unrelated work unless explicitly requested.

## Useful Commands

Use placeholders and adapt to the repository layout:

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py <reference.v> <candidate.v> --json
python3 skills/circuit-reverse-rtl/scripts/cec.py <reference.v> <candidate.v> --engine auto --smt-fallback --json
python3 skills/circuit-reverse-rtl/scripts/cec.py <reference.v> <candidate.v> --engine smt --json
python3 skills/circuit-reverse-rtl/scripts/cec.py <reference.v> <candidate.v> --engine sat-lemmas --keep-tmp --json
python3 skills/circuit-reverse-rtl/scripts/cec.py <reference.v> <candidate.v> --engine algebraic --algebraic-sliced-output <output-name> --keep-tmp --json
python3 skills/circuit-reverse-rtl/scripts/cec.py <reference.v> <candidate.v> --engine algebraic --algebraic-sliced-output <output-name> --algebraic-case-split-bit '<control[0]>' --algebraic-case-split-bit '<control[1]>' --keep-tmp --json
python3 skills/circuit-reverse-rtl/scripts/truth_describe.py <truth-file-or-dir> --json
python3 skills/circuit-reverse-rtl/scripts/truth_reverse.py <truth-file-or-dir> --out-dir <candidate-dir> --verify --json
python3 skills/circuit-reverse-rtl/scripts/truth_reverse.py <truth-file-or-dir> --out-dir <candidate-dir> --allow-boolean-fallback --verify --json
python3 skills/circuit-reverse-rtl/scripts/verify_truth_sim.py <truth-file> <candidate.v> --json
python3 skills/circuit-reverse-rtl/scripts/verify_truth_structural.py <truth-file> <structural-candidate.v> --certificate <certificate.json> --json
python3 skills/circuit-reverse-rtl/scripts/RTL_cost_calculator.py --output-dir <candidate-dir> --input-dir <reference-dir>
python3 skills/circuit-reverse-rtl/scripts/check_allowed_syntax.py <candidate.v> --allowed-syntax <allowed_syntax> --json
python3 skills/circuit-reverse-rtl/scripts/datapath_reverse.py -input <primitive-netlist.v> -output <candidate.v>
python3 skills/circuit-reverse-rtl/scripts/batch_datapath_reverse.py --bench-dir <cases-dir> --out-dir <candidate-dir>
python3 skills/circuit-reverse-rtl/scripts/gf2_solve.py solve --json '{"rows":[3,1],"rhs":[1,1],"nvars":2}'
```

If tools have been organized into subpackages, both the compatibility entry points above and the package paths may be usable:

```bash
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m verify.cec <reference.v> <candidate.v> --json
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 skills/circuit-reverse-rtl/scripts/truth_describe.py <truth-file-or-dir> --json
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m reverse.truth_reverse <truth-file-or-dir> --out-dir <candidate-dir> --verify --json
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m verify.truth_sim <truth-file> <candidate.v> --json
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m cost.RTL_cost_calculator --output-dir <candidate-dir> --input-dir <reference-dir>
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m algebra.gf2 solve --json '{"rows":[3,1],"rhs":[1,1],"nvars":2}'
```

For cached probing, prefer an existing sampler if available:

```python
from sampling.fast_sampler import PatternCache

cache = PatternCache.build("<primitive-netlist.v>", count=4096, seed=1, all_signals=True)
values = cache.bus("<output>", <width>)
ok = cache.check("<output>", lambda vec: model(vec), width=<width>)
fresh = cache.refresh(count=4096, seed=2)
```

For recurring gate-level exploration, prefer the reusable probing scripts:

```bash
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m probing.cone_deps <netlist.v> --signals <wire_or_output> [--signals <wire2>]
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m probing.match_internal_bus <netlist.v> --expr '(<python_expr>)' --width <bits> --count 512
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m probing.control_probe <netlist.v> --outputs out1:13,out2:13
```

For candidate cleanup and other Verilog rewrites, use the rewriting scripts:

```bash
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.prune_unused_gates <candidate.v> --in-place
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.prune_dead_rtl <candidate.v> --in-place
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.merge_verilog_decls <candidate.v-or-dir> [--check]
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.cost_aware_select --candidate-dir <candidate-dir> --input-dir <bench-dir> --out-dir <selected-dir> --cost-csv <syntax-cost.csv>
```

For Boolean fitting, use the GF(2) helpers instead of reimplementing row reduction:

```python
from algebra.gf2 import fit_bits, formula_expression, monomial_terms

terms = monomial_terms(["a", "b", "c"], max_degree=2)
coeffs = fit_bits(samples, output_bits, terms)
expr = formula_expression(coeffs, terms)
```

## Heuristics

- Test orientation variants: raw, reversed bit order, complemented bits, swapped halves, and packed field reorderings.
- For wrapped arithmetic, distinguish full-precision arithmetic from per-term truncation and sum-then-truncation.
- For ICCAD22-style primitive netlists, try the bundled automated learners before hand-written case work: quadratic/cubic integer expression fitting, small signed-difference predicates, 2-bit product muxes, offset-add-with-compare patterns, affine/control sums, and conditional multiply-accumulators. These learners validate by simulation. Run cost-aware selection only after candidate generation if the benchmark rewards a fallback or rewrite over the generated RTL.
- For signed arithmetic, independently test data signedness, coefficient signedness, shift signedness, and comparison signedness.
- One-hot probes are not enough. Add MSB-only, all-ones, zero, alternating-bit, boundary, and random vectors.
- Carries, mux controls, decoded enables, and partial sums often appear as internal nodes. Sample internal pins when the tool can expose them.
- For output expressions that look like `base +/- selected`, isolate controls and recover unknown branches by modular subtraction from sampled output words.
- Signed narrow operands can masquerade as wraparound or interval logic. Test explicit sign extension and `$signed` forms, then let CEC decide.
- Verilog expression sizing is semantic. Use sized neutral terms or explicitly sized intermediates when a Python model and RTL disagree by a truncation bit.
- For multi-output circuits, learn shared intermediates once and derive flags from those intermediates.
- For fixed-point behavior, check rounding, saturation, low-word extraction, high-word extraction, and arithmetic-vs-logical shifts.
- For learned formulas, refresh samples with a new seed and then run formal validation.
- For IWLS/ABC `.truth` files, remember that `read_truth -xf` uses complemented input indexing; use `truth.utils.read_truth_words` or the bundled `truth_reverse.py` / `verify_truth_sim.py` wrappers so formulas are inferred and checked in normal Verilog `x` order.
- For floating-point truth tables, infer and report the semantic contract first: input/output format (for example BF16 or FP16), operation, rounding mode, DAZ/FTZ behavior, NaN canonicalization, infinities, signed zero, and saturation/overflow behavior. Then use that description to design RTL or approximation/refinement structure.
- For truth-table reversal, do not emit benchmark-name dispatch, case-specific answer tables, flat input-enumerating `case` tables, or field-factored LUTs unless the user explicitly opts in. Prefer reusable recognizers and structural emitters such as arithmetic, sqrt/division, fixed-point range-reduced transcendental evaluation, popcount, bit projection, and GF(2) affine outputs.

## Deliverable

Report:

- Generated RTL path.
- Validation command and result.
- Whether validation was a strict proof (`pass`) or a non-strict result (`pass (non-strict)`). Final promoted RTL should have a strict proof; if only non-strict exploration evidence exists, state that equivalence is not strictly guaranteed and do not present it as final.
- Cost command and result when relevant.
- Inferred function family or decomposition.
- Any unresolved risk, especially if a weaker validation result was accepted by user instruction.

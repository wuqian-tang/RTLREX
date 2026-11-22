---
name: circuit-reverse-rtl
description: Recover compact, exact combinational word-level RTL from truth tables, AIGs, or primitive-gate Verilog, with strict verification and cost-aware refinement.
---

# Circuit Reverse RTL

Recover the circuit's complete behavior as synthesizable combinational RTL. Preserve the required top name, ordered ports, directions, exact packed ranges, widths, signedness, and output packing. Infer from the supplied circuit; do not dispatch on benchmark names, published answers, golden-derived constants, or distinctive interface shapes.

## Select the input route

Locate this package using the supplied Skill path; scripts and references below are relative to its directory. The package can be installed outside a repository. Check available engines with `command -v yosys abc iverilog vvp z3`; environment/tool configuration may supply other paths.

### Complete truth tables: secure a result first

ABC `read_truth -xf` stores output y[j] in nonempty line j, with character zero at the left. For normal unsigned input x, character index is `(~x) & ((1 << n) - 1)`; x[0] is the least significant input bit. The complement is on the input index, not the output. Use the bundled reader rather than trying orientation variants after this contract is established.

Run the budgeted recovery tool directly; it infers a semantic candidate, verifies the fixed Yosys frontend and complete input domain, measures syntax cost, and immediately saves the verified output. When the task permits exact Boolean fallback, include `--allow-boolean-fallback` in this first invocation so unrecognized functions can still produce a validated checkpoint:

```bash
python3 <skill-dir>/scripts/recover_truth.py <input.truth> <final.v> --budget-seconds 240 --json --brief
```

Adapt the internal budget to the user's remaining wall time. This command includes its own tools in the budget. Its JSON reports family, verification, cost, retained output and attempt records. Read that report instead of separately repeating `truth_describe`, generation, verification and cost for the same input. A completed exact check of unchanged bytes is sufficient for the local workflow; independent evaluations recheck the terminal file.

**The verified output is a managed, write-protected checkpoint.** Generate a proposed improvement under another name, then let the tool validate and atomically promote it only if cost improves:

```bash
python3 <skill-dir>/scripts/recover_truth.py <input.truth> <final.v> --candidate <proposal.v> --budget-seconds 120 --json --brief
```

`--brief` keeps stdout small while `report_path`, `first_checkpoint.receipt_path` and `selected_checkpoint.receipt_path` identify the complete durable evidence. Omit it when the full proof report is needed. A failed, more expensive or timed-out proposal leaves the verified output intact. After publishing the first exact checkpoint, the output-bound journal permits at most two proposals within a 120-second wall-clock window, including time between CLI calls; two consecutive non-improvements stop refinement. Failures, timeouts and interrupted attempts consume a proposal. Repeating the CLI or changing `--state-dir` cannot reset these limits. `--max-cost-proposals`, `--refinement-seconds` and `--max-non-improvements` can only reduce the policy when creating the first checkpoint. The tool refuses to overwrite an existing output without a matching local receipt. Use a fresh target for an unrelated retained file. Do not spend the entire task budget optimizing before saving a first exact result. Reserve time for the response; stop when the remaining time cannot cover another exact check.

Do not edit, copy over, rename over, unlink or change permissions on the managed output. Only the recovery tool may replace it, using a successful `--candidate` promotion. An independent check of a separate proposal does not authorize bypassing this journal or its deadlines. Once refinement stops, finish the task using the retained checkpoint; do not continue unrestricted optimization or adopt a later proposal manually. Write protection prevents ordinary accidental overwrites; it is not a security boundary.

Before the final response, confirm that the submitted bytes are the selected checkpoint:

```bash
python3 <skill-dir>/scripts/recover_truth.py <input.truth> <final.v> --check-checkpoint --json --brief
```

This checks the current truth, complete proof receipt, first checkpoint, canonical journal and final source hash, without another solver call or proposal and without resetting the refinement window. Submit only on `checkpoint_validated`; otherwise retain the diagnostics and report the unresolved final obligation.

If no semantic match is found, use the agent's own analysis and helpers to investigate guards, fields and arithmetic. `truth_describe.py` can expose the matched semantic contract when diagnosis is needed; it is not a required extra invocation before recovery. Read [truth-table workflow](references/truth_table_workflow.md) for floating-point conventions, bounded refinement and fallback.

If the task permits exact Boolean fallback, add `--allow-boolean-fallback`. The generator compares ordinary and complement-edge BDDs under bounded variable orders, shares ANF factors, and tests output-function reuse under input permutations against the complete table. It selects by the active syntax weights; source bytes or node counts alone do not predict frontend effort. Shared Boolean logic remains low-level, including packed Boolean function returns. Input-enumerating LUTs, truth-derived case tables, embedded truth strings and field lookup tables require explicit user authorization; intermediate exhaustive analysis is allowed. Recovery metadata alone is not an independent high-level representation audit.

### Primitive-gate Verilog

Build a source oracle and try `scripts/datapath_reverse.py` before hand-solving cones. Recover word arithmetic and control from input/internal signals, then certify the complete original-to-candidate pair. Prioritize unresolved primitive cones before cosmetic rewriting. Read [gate-level probing](references/gate_level_probing.md) for sampling, bus matching and control decomposition; read [algebraic fitting](references/algebraic_fitting.md) for GF(2), ANF and modular coefficient solving.

### AIG or proof archives

Read [AIG cases](references/aig_cases.md). Prove every primary-input cofactor and reconnect all bridges to the original circuit. An easy intermediate RTL pair alone does not establish the original equivalence obligation.

## Exactness and synthesis constraints

- Emit combinational RTL with explicit widths and signed intermediates. Verilog sizing, truncation and arithmetic shifts are semantic, not cosmetic.
- Encoders, normalizers and iterative arithmetic use statically bounded loops with complete assignments. Avoid data-dependent `while`, state, latches, delays and non-synthesizable constructs.
- Promote only after complete exact equivalence and frontend acceptance. Random simulation and `pass (non-strict)` are exploration evidence, not final proofs. Counterexamples, conflict, cancellation, abnormal termination, timeout and partial output/case coverage cannot become pass.
- For netlists, start with `scripts/cec.py reference.v candidate.v --engine auto --strict-cec --json`. If inconclusive, select an exact route based on the structure: arithmetic SMT, algebraic replay, output-bit SAT or checked composition. Read [exact CEC](references/exact_cec.md) for commands, support boundaries and certificate invariants; avoid repeatedly increasing the same stalled timeout.
- The SMT miter must include every output equality and enabled assertion. New Yosys requires `chformal -lower` before serialization; the checker audits individual and aggregate assertion dependencies. Never replace this with an unchecked solver `PASSED` string.
- On mismatch, use the first counterexample to inspect input/output orientation, guard priority, sign extension, widths, rounding and exceptional values. A matching Python model does not excuse a failing RTL implementation.

## Cost-aware refinement

After saving exact RTL, optimize the user's metric. Read [RTL rewriting](references/rtl_rewriting.md) when remaining time supports a verified improvement. Use `scripts/RTL_cost_calculator.py` with the active CSV; use `scripts/check_allowed_syntax.py` before selection when the benchmark provides a syntax whitelist. Charged helpers, functions, submodules and keywords must actually be allowed.

Useful reusable transformations include shared word intermediates, bounded arithmetic recurrences, removal of dead logic, explicit width/sign cleanup, grouped declarations and equivalent constants. Broad identity or constant endpoint regions inferred from the supplied oracle can gate a floating-point core only after complete-domain verification; isolated input-answer repairs are prohibited. After Yosys lowering, an output mux alone may leave the expensive arithmetic active. Isolate the complete core operand explicitly and verify the lowered data path and every input under the unchanged deadlines. Preserve that operand isolation when combining guards or sharing helpers: fewer source operators or lowered cells can still cause much more wide arithmetic to run. A proposal must complete within the bounded recovery workflow; a separate proof close to the external deadline is insufficient reason to replace the checkpoint. A loop is suitable for arithmetic iteration; it must not conceal input enumeration or a lookup table. Coefficients should follow the inferred semantic algorithm, and every precision or loop-bound change requires complete verification. Keep lower-cost verified RTL before attempting another simplification. Readability breaks ties; synthesis area and timing require their own measurements. Selected packed bits, packed word slices and unpacked array elements have different widths. The syntax scorer records these declarations but remains a lexical proxy, with limitations for parameter expressions and scope; do not call its score a gate count or hardware area.

The semantic emitter shares repeated input fields and exact rounding operations and uses bounded word algorithms for roots and power quotients. Compare the complete alternatives before selecting: a word helper used once can add a return-range selection without removing a repeated operation, so retain its direct visible expression when the signed-width contract is preserved. Preserve the complete exceptional-value and rounding contract when simplifying guards. Concatenation contents are charged normally; moving arithmetic into braces does not remove its cost. Reusing a genuine helper can reduce source syntax, but repeated calls do not establish physical circuit sharing. Keep every charged operation visible, and measure the resulting RTL with the task's fixed scorer and CSV.

Fold format-derived constants before emission, including fixed rounding biases, while retaining every required rounding stage. A signed-width helper cannot process a wider unsigned reduction; preserve each intermediate's full width. For small integer roots, compare bit-prefix search, ascending numeric search and monotone arithmetic descent under the active CSV. Descent starts at the largest root and subtracts the Boolean test that its square exceeds the radicand; widen the comparison to the full square width, including for odd input widths. Wider domains keep the bit-prefix route. Lower source cost does not establish lower synthesis area.

When a reference cost is supplied, compare each valid pair as well as aggregate costs. A tie at a demonstrated cost lower bound is a tie; a reference without a verified final has no numerical cost comparison. Do not hide computation, alter the price profile or discard difficult pairs to claim improvement.

For finite-only floating-format hypot, retain the matched encoding contract: the largest magnitude payload is NaN, all other payloads are finite, and overflow saturates. A bounded search from the larger input code can compare exact squared numeric midpoints; it is an arithmetic recurrence, not an input lookup. An IEEE infinity/NaN contract requires its own guards. Periodic range reduction must retain its full product precision and a guard bit for quotient rounding. Simplify rounding control only after a format-wide proof excludes ties; preserve the signed residual and every later rounding stage. See the [truth-table workflow](references/truth_table_workflow.md) for width and guard requirements.

## Deliverable

Report the selected RTL path, inferred behavior, exact verification method/result and measured cost. Include `first_checkpoint` and `selected_checkpoint` from the recovery report, so the first proof remains traceable after an improvement; report any refinement stop reason. Distinguish high-level recovery from Boolean fallback and strict proofs from exploratory checks. If no exact terminal implementation is secured, report the unresolved obligation and keep diagnostic candidates separately.

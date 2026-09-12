# RTL Rewriting After Gate-Level Reversal

Use this reference after all remaining primitive-gate cones have been replaced by verified word-level RTL. At this point, optimization should reduce the local cost model without changing the already-proved behavior.

## Order Of Operations

1. Run CEC or a strong random sample check on the fully reversed RTL.
2. Remove dead primitive gates:
   ```bash
   PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.prune_unused_gates <candidate.v> --in-place
   ```
3. Remove dead continuous assigns and unused wire declarations:
   ```bash
   PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.prune_dead_rtl <candidate.v> --in-place
   ```
4. Measure cost.
5. Apply one low-risk rewrite class at a time.
6. After each rewrite class, rerun fast random sampling and then CEC before promoting.

## Low-Risk Cost Rewrites

- Delete dead scaffold left from bus matching: unpacking assigns such as `assign {w__...} = expr;` are often unused after output cones are replaced.
- Prefer shared intermediates for repeated add/sub terms if the cost model charges duplicated operators.
- Reuse an already-computed output when another output contains the same subexpression, such as rewriting `c - a - b` as `c - sum_ab` after proving `sum_ab = a + b`.
- Factor common multiplicands before promotion: rewrite `a*b + a*c + a*d` as `a*(b+c+d)` when widths and truncation preserve behavior.
- Replace explicit replication concat sign-extension with a signed cast only after checking Verilog width behavior and CEC:
  `wire signed [12:0] sx; assign sx = $signed(narrow);`
- Remove redundant zero-extension concats when the destination expression already forces the intended width.
- Add a wider neutral term when a sum must not truncate to a narrow operand width:
  `13'd0 + in28 + in42`.
- Collapse carry-save output scaffolding into one verified word-level expression once the final word matches. Do not require each carry-save operand to have a clean behavioral meaning.

## Validation Traps

- A Python model can silently use full-precision arithmetic while Verilog truncates at operand width. Check mismatches for one-bit offsets near width boundaries.
- `$signed(x)` extends according to the destination expression or assigned wire width. If uncertain, assign to an explicitly sized signed intermediate and validate.
- Cost-only rewrites can still change semantics. Treat each rewrite as a candidate requiring random sampling and CEC.
- Treat a provided allowed-syntax file as a hard whitelist. Run `scripts/check_allowed_syntax.py` before cost comparison; reject helper-based candidates when declaration keywords such as `function/endfunction` are absent, even if CEC passes and the cost calculator reports a lower number.
- Do not start these rewrites while primitive output cones remain unexplained unless the gate-level path is blocked; otherwise cost cleanup can hide useful structural clues.

## Useful Commands

```bash
python3 skills/circuit-reverse-rtl/scripts/RTL_cost_calculator.py --detail <candidate.v>
python3 skills/circuit-reverse-rtl/scripts/check_allowed_syntax.py <candidate.v> --allowed-syntax <allowed_syntax> --json
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m verify.cec <reference.v> <candidate.v> --json
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.prune_dead_rtl <candidate.v> --in-place
```

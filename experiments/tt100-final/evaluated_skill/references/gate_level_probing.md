# Gate-Level Probing

Use this reference when the source or remaining candidate logic is still primitive-gate Verilog.

## Practical Flow

1. Build a sampling oracle with `sampling.fast_sampler` from the skill scripts. Set `PYTHONPATH=skills/circuit-reverse-rtl/scripts` when importing it from ad hoc Python.
2. Trace input cones before guessing formulas:
   ```bash
   PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m probing.cone_deps output/test27.v --signals out1 --signals w__2282
   ```
3. Probe controls in all-zero, one-hot, paired, and random-combination modes. One-hot matches do not prove priority or arbitrary combined-control behavior.
4. Match candidate word-level expressions to internal bit wires:
   ```bash
   PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m probing.match_internal_bus output/test27.v \
     --expr '(in1 + (in21 if not in22 else -in21) + in13 + in23 + in24) & mask' \
     --width 13 --count 512
   ```
5. Replace only verified full buses or subchains. Preserve bit order deliberately.
6. After a bus replacement, recursively prune unused primitive gates with the rewriting helpers:
   ```bash
   PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.prune_unused_gates output/test27.v --in-place
   ```
7. When a cone has been fully replaced by RTL, remove dead RTL scaffolding as well:
   ```bash
   PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m rewriting.prune_dead_rtl output/test27.v --in-place
   ```
8. Run CEC before promoting a candidate.

## Branch Isolation Pattern

Use this when an output looks like a muxed arithmetic cone but one branch remains unclear.

1. Force all unrelated controls to fixed values, then enable the target branch.
2. If the output has the shape `base +/- selected`, compute the unknown side by modular subtraction:
   `base = out - selected` or `selected = base - out`, masked to the output width.
3. Split by the highest-suspicion control first. For example, test `in30=0` and `in30=1` separately before trying broad expression searches.
4. Fit simple candidate terms first: shared partial sums, selected input buses, sign-extended narrow operands, and one extra addend.
5. Validate the recovered branch under random combined controls, not only one-hot controls.

## Heuristics

- Carry-save outputs often appear as two word buses plus a one-bit carry term. Probe each part, but validate the final word because the parts may not map cleanly to source operands.
- Multi-control datapaths may not be priority muxes. If one-hot probes fit but random combined controls fail, learn the control Boolean function separately or keep the surrounding gate network.
- Sign-extension often appears as repeated MSB matches on high bits. Confirm whether extension happens before or after addition.
- A branch whose outputs are sometimes near the modulus boundary may be a sign-extended narrow operand, not interval logic. Check `{{k{x[msb]}}, x}` and `$signed(x)` variants early.
- Verilog expression width is part of the function. If `a + b` truncates because both operands are narrow, force the intended width with a wider neutral term such as `13'd0 + a + b`.
- Internal vector sampling is preferred over testbench rewriting when the sampler supports the candidate's assigns and bus expressions.

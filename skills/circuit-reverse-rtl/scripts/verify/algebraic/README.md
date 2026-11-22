# Conservative algebraic combinational equivalence

```
PYTHONPATH=skills/circuit-reverse-rtl/scripts python3 -m verify.algebraic \
  --reference /absolute/primitive.v --candidate /absolute/candidate.v \
  --out /absolute/new-proof-directory --term-cap 100000 --timeout 120 \
  --yosys /absolute/yosys --sliced-output difficult_word \
  --case-split-bit 'mode[0]' --case-split-bit 'mode[1]'
```

The caller must enforce an overall subprocess/process-group timeout. A completed
run writes `result.json` with `status=pass|unknown|error`; only `pass` sets
`equivalent=true` and `strict=true`. Unsupported syntax, resource exhaustion,
nonidentical polynomials, and failed proof checks do not establish a functional
counterexample and return `unknown`.

The proof chain is self-contained and does not read paper snapshots or case
names. The primitive network is parsed conservatively. Each discovered local
two- or three-leaf adder identity is independently evaluated on all four or
eight assignments against its ORIGINAL gates; no relationship among cut leaves is assumed.
Two separate sparse-polynomial implementations then eliminate the network's
internal variables in the Boolean quotient ring over integers modulo 2^W.
Acyclicity, complete output coverage, and a final primary-input-only polynomial
are checked. The independently derived candidate word polynomial must match.
For each `--sliced-output`, both implementations instead reduce the exact
reference-word-minus-candidate-polynomial goal by output significance. The
candidate polynomial is never assumed, primary inputs remain free, and only a
zero final remainder passes.

Each `--case-split-bit` names an original primary-input bit. The checker
constructs and proves the complete Boolean cube over all listed bits and rejects
incomplete coverage. Every unsplit primary input stays free in every branch;
therefore the split is an exhaustive proof decomposition rather than an input
assumption. Case-split mode requires every output to be significance-sliced.

The candidate frontend currently accepts unsigned full-word add/sub/mul and
scalar mux cells. A mux selector may be a primary bit or a small unsigned
two-state comparison, logic/reduction operation, or scalar bitwise cell whose
primary support is exhaustively evaluated. Cell results use the compared output
width or require the separately checked unsigned range bound described below.
Primary bits/constants can be extended by explicit wiring; a shifted prefix of
a full-width internal bus is handled by the exact modular left-shift identity.
Other internal slices, unbounded different-width arithmetic results, signed
cells/ports, large or internally driven selectors, and unknown cells fail closed. The source and
serialized interfaces must use matching ordered names and zero-offset descending
unsigned ports. At least one output is required. Python `-O` is rejected because
the independent certificate checks use assertions.

This implementation is not a general Verilog symbolic simulator. Source hashes,
Yosys version bytes, all local identities, primary and replay polynomials, the
candidate lowering log, and immutable copies of the verifier Python sources are
retained for review. No original candidate or canonical dataset is changed.

The reviewed range extension removes high reference bits only when their
original gate cones prove constant zero without primary-input assumptions.
The candidate is still translated in the full declared-width ring. A structural
unsigned range proof must place its value below the reduced modulus,
establishing that the omitted candidate high bits are also zero. Narrow add and
multiply results propagate operand bounds; a mux uses the maximum branch bound.
The checker refuses a narrow result when that proof cannot exclude wraparound,
including narrow subtraction. Signed arithmetic remains unsupported. Low-bit
equality alone never certifies a larger output word.

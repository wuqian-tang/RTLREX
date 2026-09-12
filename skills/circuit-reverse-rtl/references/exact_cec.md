# Closing inconclusive combinational proofs

Preserve the original reference, candidate, interface, and their hashes. A
different proof route must establish equivalence of that same pair. Do not
substitute a known-easy RTL candidate or a local golden model without proving
the connecting obligations.

## Verified algebraic reduction

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v \
  --engine auto --strict-cec --abc-timeout 15 --algebraic-fallback \
  --algebraic-timeout 120 --algebraic-term-cap 100000 \
  --keep-tmp --tmpdir proof --json
```

Use `--engine algebraic` to invoke the algebraic stage directly. The stage
currently supports a single-module primitive reference and a conservative
unsigned RTL subset (word addition, subtraction, multiplication, scalar mux,
and supported wiring), with explicit interfaces. An unsupported construct
returns inconclusive rather than relaxing its semantics.

A separate signed-arithmetic frontend supports addition, subtraction, and
multiplication followed by exact sign or zero extension. It interprets operands
with their RTLIL signedness and derives an interval bound for each native
result. Lifting a result narrower than the comparison ring requires its entire
range to fit the consumer's signed or unsigned domain; possible native overflow
is rejected. This supports full-width signed products accumulated in a wider
word. Internal right shifts, nontrivial truncation, and mixed signedness remain
unsupported in this path. `word_signed.py` is retained with the replay sources.

For arithmetic cones that expand poorly, use the separate complete-cone backend:

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v \
  --engine algebraic-cones --algebraic-cone-input-cap 6 \
  --algebraic-timeout 120 --algebraic-term-cap 200000 \
  --keep-tmp --tmpdir proof --json
```

It replaces small cones by exact integer multilinear polynomials over their
original primary-input support (at most six inputs by default, hard maximum
eight). Every support assignment is evaluated; this is not random simulation.
Independent replay evaluates the original gates and derives coefficients with
a separate subset-inclusion implementation before repeating the full output
reduction. All original inputs remain free. This engine rejects case-split and
sliced-output options; it proves every output with a full-goal reduction.

For a difficult arithmetic output, request significance-sliced reduction:

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v \
  --engine algebraic --algebraic-sliced-output out1 \
  --algebraic-timeout 1800 --algebraic-term-cap 1000000 \
  --keep-tmp --tmpdir proof --json
```

This forms `reference_word - candidate_polynomial` as the proof goal and
reduces it from the most significant slice to the least significant slice.
The candidate expression is not an input constraint. All primary inputs stay
free, and only a zero final remainder proves equivalence. The certificate
checker independently lowers the retained candidate and repeats the sliced
reduction. Repeat `--algebraic-sliced-output` for multiple named outputs.

For a small control field, an exhaustive Shannon decomposition can reduce the
intermediate polynomial without weakening the proof:

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v \
  --engine algebraic --algebraic-sliced-output out1 \
  --algebraic-case-split-bit 'mode[0]' \
  --algebraic-case-split-bit 'mode[1]' \
  --algebraic-timeout 1800 --algebraic-term-cap 1000000 \
  --keep-tmp --tmpdir proof --json
```

The checker constructs all `2**k` assignments internally and rejects duplicate,
unknown, missing, or incomplete split sets. Every output must use sliced
reduction in this mode. Each branch fixes only the listed primary bits; all
other primary inputs remain free. A complete-cube check and a zero remainder
for every branch compose the branch results into full-input equivalence. This
is exhaustive case analysis, not an environmental assumption. Both implementations
use branch-local interned expression identifiers to avoid repeatedly expanding
shared Boolean DAGs; input identities and inversion phases are preserved.

Each recognized half- or full-adder identity is checked over all assignments of
its two or three independent cut inputs, using the original gates. Identities may
include complemented sum/carry phases. The original output's weighted bit sum
is then reduced using exact gate polynomials over integers modulo `2**W`, with
Boolean variables satisfying `x*x=x`. An independent implementation rechecks
the local identities, rejects cyclic rewrites, repeats the global elimination,
and compares against the word-level polynomial derived from the retained RTL
through Yosys. Every original output and its full width must be covered.

The candidate frontend may lower a scalar mux condition from an unsigned
two-state comparison, logic/reduction operation, or bitwise scalar cell when
the cell operands are primary bits/constants and the independent support has at
most eight bits. It evaluates the complete support truth table and derives its
unique integer multilinear polynomial; signed or larger/internal condition
cones fail closed. Narrow mux results use the maximum of the two structural
operand bounds. Narrow add/multiply results require an overflow-free structural
bound, and narrow subtraction remains unsupported.

Keep the local identities, independent replay, source/tool hashes, and final
`result.json`. The proof trusts the audited Python arithmetic implementation
and Yosys RTL elaboration; it is an exact algebraic proof, not a SAT solver
certificate. A polynomial term limit or time limit produces inconclusive
status. The outer CEC watchdog covers extraction, both reductions, and replay;
termination overrides any partial success output. The independent record keeps
byte-for-byte copies of the algebraic verifier sources. Python `-O` is rejected
because the certificate checker requires its invariant checks enabled.

## Independent output-bit SAT

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v \
  --engine sat-bits --timeout 120 --sat-bit-timeout 15 \
  --sat-total-timeout 300 --keep-tmp --tmpdir proof --json
```

The frontend constructs one equality for every output bit, checks the flattened
model, and rejects unsupported state/formal cells or undefined values. Each SAT
query retains only its output cone and leaves the shared primary inputs free.
Undefined-value modeling is enabled with defined primary inputs: an undefined
equality cannot satisfy the ordinary `-prove ... 1` obligation. A failed query
can identify a value mismatch or an undefined output; replay its witness to
distinguish these cases.
There are no cutpoint assumptions, simulation-based constraints, or assumptions
that other output bits agree. `coverage.json` identifies proved, failed, and
timed-out bits by output name and offset from its least significant end. A
counterexample includes the generated miter's `pi_N` input values; their mapping
to the source ports is explicit in `miter.v`.

The SAT budget is the complete bit-checking stage; frontend lowering has a
separate timeout. Only complete coverage yields `pass`. Partial coverage can
identify the remaining difficult cones, but is not a certificate of the word or
the circuit. The route can still time out on structurally different multipliers.

## Cumulative proved-lemma SAT

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v \
  --engine sat-lemmas --timeout 120 --sat-bit-timeout 120 \
  --sat-total-timeout 1800 --keep-tmp --tmpdir proof --json
```

This mode proves output equalities in interface order and least-significant-bit
order. The first duty is assumption-free. A later duty may set only earlier
equalities whose SAT queries already returned `pass` in the same certificate
chain. The chain stops immediately on timeout, unknown, error, or
counterexample; no later query may cite that duty. `coverage.json` records the
exact predecessor indices used by every query. Only a complete proved prefix
covering every output bit yields `pass`.

## Further decomposition

For small cones, exact exhaustive enumeration over **all** their independent
support inputs can establish an internal correspondence. Larger cones need a
formal proof. Random signature matches are useful proposals, not lemmas.

Before replacing corresponding internal signals with common free inputs, prove
their equality from the original primary inputs. Check dependency order so that
lemmas cannot justify themselves or each other circularly. Then prove every
original output under the abstraction. Keep both the lemma proofs and the
residual proof, and reject the overall result if any obligation is inconclusive.

Synthesis normalization can expose shared structure. Record both transformations
and compare all outputs. When relying on the synthesis frontend as trusted,
state that trust explicitly; do not describe an unverified rewrite as an
independently certified transformation.

## Arithmetic engine boundary

`cec.py --engine acec` is a historical alias for ordinary ABC `&cec`; it does
**not** invoke ABC's separate arithmetic command `&acec`.

Do not bypass the checker by treating arbitrary `&acec` output as a certificate.
ABC's separate arithmetic command can rewrite arithmetic boxes and output
structure internally; this package does not admit it as a full-interface proof
backend. The release does not include ABC source or binaries. A prospective
backend needs a version-specific source review and positive/negative tests,
including mutations of the final output bits, before use. Replaying a reported counterexample against the original
Verilog distinguishes an actual mismatch from a tool/translation failure; failure
to replay does not prove equivalence.

## Native terminal residuals

```bash
python3 skills/circuit-reverse-rtl/scripts/cec.py reference.v candidate.v \
  --engine algebraic-terminal --algebraic-coefficient-input operand \
  --algebraic-timeout 180 --algebraic-term-cap 300000 --keep-tmp --json
```

Use this route when expanding a long Boolean cone destroys an otherwise useful
arithmetic polynomial. Repeat `--algebraic-coefficient-input` for the original
input ports supporting that cone. The checker retains original native gate
functions, independently replays the complete reference-minus-candidate
residual, constructs all coefficient obligations over those functions, and
proves every coefficient zero by strict ABC CEC. These functions are not free
cutpoints, and their relations are never assumed. All original inputs remain
free. Input-port choices guide decomposition; they do not constrain values.

The current backend supports exactly one complete output word, the documented
word-polynomial subset, and complete small-input cones (default 6, maximum 8
primary inputs). It does not accept case-split or sliced-output CLI options.
A missing coefficient proof, changed source, timeout, unsupported expression,
or nonzero residual remains inconclusive. It snapshots checker sources and
hashes, pins the input pair, and applies a descendant-process watchdog. The
coefficient frontend receives the remaining overall stage budget; its ABC
solver cap is separate, and neither can extend the overall deadline. A
projection alone proves only that projection; use a checked composition or
embedding connector before claiming equivalence of a larger original pair.

## Explicit, checked composition plans

```bash
python3 skills/circuit-reverse-rtl/scripts/verify/composition.py \
  --plan proof_plan.json --out fresh_composition_proof \
  --yosys /absolute/path/to/yosys --timeout 120 --term-cap 200000
```

The plan binds `reference_aig`, `candidate_aig`, `bridge_rtl`, and
`word_stage_rtl` using `{ "path": "/absolute/path", "sha256": "..." }`
records. Include `original_reference` and `original_candidate` records to
certify the original RTL pair: the checker constructs adapters with the exact
source interfaces and independently proves each original-to-AIG bridge.
Without these two records, its result covers only the supplied AIGs.

`tap_literals` lists distinct internal reference AIG nodes (optionally inverted)
in bridge-output order. `word_outputs` lists distinct original output indices
in word-stage order. The bridge has `pi[I-1:0]`/`po[T-1:0]`; the word stage has
`pi[I+T-1:0]`/`po[W-1:0]`, with original inputs in the low bits and taps above.
The checker proves every bridge bit from the original inputs, proves the word
stage with the taps free, reconnects the bridge and checks the candidate, then
proves all remaining outputs using only the established word equalities.

`tap_engine` can be `auto`, `algebraic`, or `algebraic-cones` (`auto` by default).
For independent arithmetic tap words, `tap_word_widths` must partition every
tap bit in order; the checker constructs and checks the complete grouped
interfaces. `word_engine` accepts the same engines. Omitting it selects the
conservative algebraic replay with word-cell widths preserved. Unsupported
partial expressions or groups fail closed. Each proof stage has a bounded
budget; a partial stage never yields a full proof. The checker retains all
commands, RTLs, and results. Tap discovery, word grouping, and the bridge and
word hypotheses remain explicit plan construction tasks, not automatic
inference claimed by this verifier.

## Certified normalization and RTL chains

```bash
python3 skills/circuit-reverse-rtl/scripts/verify/normalize_final_adder.py \
  --plan affine_plan.json --out fresh_normalization --timeout 120
python3 skills/circuit-reverse-rtl/scripts/verify/chain.py \
  --plan rtl_chain.json --out fresh_chain --timeout 180 --term-cap 1000000
```

A final-adder plan supplies `reference` (`path`/`sha256`), `output_name`,
`cutnames`, integer `weights`, and an integer `constant`. Signed powers of two
are interpreted modulo that output width. The normalizer constructs a
compressor/ripple implementation, preserves the original logic feeding other
outputs, and requires strict CEC of **every original output** before reporting
success. Discovery and affine-weight fitting remain proposal steps; an
unproved free-cut identity does not certify the rewrite. The normalized RTL is
a proof intermediate, not a replacement for the retained paper candidate.

A chain uses `schema: "exact-rtl-chain/v1"`, `nodes` containing ordered
`path`/`sha256` records, and exactly one `edges` entry per adjacent pair. Every
node must preserve the complete ordered source interface. Each edge specifies
`engine`: `auto`, `smt`, `sat-bits`, `sat-lemmas`, `algebraic`, or
`algebraic-cones`. Algebraic edges may supply `sliced_outputs` and
`case_split_bits` within the selected engine's support boundary. Every adjacent
pair is proved anew with strict checking; all node hashes are rechecked before
success. An incomplete edge leaves the entire original-endpoint claim unknown.
Choosing useful intermediate RTLs and edge engines remains an explicit plan
construction step.

## Complete wider-word embeddings

```bash
python3 skills/circuit-reverse-rtl/scripts/verify/embedded_word.py \
  --plan embedding_plan.json --out fresh_embedding \
  --timeout 180 --term-cap 300000
```

For a right-truncated arithmetic output, a proposed embedding can restore low
bits and expose a complete polynomial word. The plan binds `reference`,
`candidate`, `embedded_reference`, and `word_candidate` with `path`/`sha256`
records and sets `low_bits`. The wider output width must equal the original
width plus `low_bits`. Choose `engine` from `algebraic`, `algebraic-cones`, or
`algebraic-terminal`; the latter also takes a `coefficient_inputs` list.

The checker requires every original primitive gate to remain identical, all
original input bits to remain free, and every high embedding output to be the
corresponding original output bit through exact buffer aliases. It proves the
entire wider word, generates its own high-bit projection adapter, and strictly
checks that adapter against the retained candidate. Low bits are proved, never
assumed. Current support is one complete original output word with the
algebraic frontend's explicit unsigned, zero-based descending interfaces.
Constructing a suitable embedding and word hypothesis remains an agent-guided
proposal step; proving a separately edited projection does not substitute for
this full original-pair connector.

## Complete grouped algebraic case covers

```bash
python3 skills/circuit-reverse-rtl/scripts/verify/grouped_algebraic.py \
  --plan grouped_plan.json --out fresh_grouped_replay \
  --timeout 300 --term-cap 300000 --jobs 4
```

Use explicit outer groups when more control bits are needed than one algebraic
invocation supports. The plan has `schema: "exact-grouped-algebraic/v1"`,
`reference`/`candidate` hash records, `fixed_bits`, and `groups`. Every group
supplies `assignment` (a Boolean value for every outer fixed bit),
`reference`/`candidate`/`identities` hash records, and optional `split_bits`.
Each artifact record has `path` and `sha256`; `identities` is a local-adder
identity file produced by the algebraic backend for that group's reference.

The checker requires exactly every outer assignment once and verifies that
each group source differs from its original only by the declared input-bit
substitutions. It then **reruns independent certificate replay** over the
complete inner Boolean cube, checking all original gates, local identities,
word outputs, and free-input scope. Existing result labels are not certificates
accepted on trust. The CLI timeout bounds each entire group subprocess and its
descendants; all groups must finish successfully. Source/checker hashes are
checked again before issuing the complete-cover result.

The current input grammar deliberately supports a primitive reference and one
flat candidate module with explicit `wire`/`assign` statements; strings, macros,
lexical scopes, and primitive drivers of inputs or constants are rejected. Outer fixed
bits must be explicit vector input bits; their ports may be referenced only
through individual bit selections, so whole-bus uses or part-selects cannot
silently escape cofactoring. There are at most 12 outer fixed bits and 8 inner
split bits per group. An agent proposes the partition and source files; this
checker verifies the proposal. The result certifies exactly the supplied
source pair, which may still be a conditional or projected subproblem needing
its original-circuit composition links.

## Typed product-prefix identity

```bash
python3 skills/circuit-reverse-rtl/scripts/verify/typed_product.py \
  --left product_left.v --right product_right.v --out fresh_product_identity
```

This focused checker handles the same unsigned product represented at different
native widths. It lowers both actual sources through Yosys, requires each full
output to be the low prefix of one `$mul` result, checks all operand bits are
directly wired original inputs or Boolean constants, and compares canonical
Boolean polynomials modulo the output width. Native multiplication widths may
differ, provided both cover every compared low bit. No signed operand,
unsupported driver, or unproved value bound is admitted.

For native width $N\ge W$, taking the low $W$ bits of a product modulo $2^N$
gives the product modulo $2^W$. This exact identity permits a complete proved
product word to become a common free cut in a separate residual check.
Certifying the local product alone does not prove a larger circuit: also check
the source-to-product connections, that every discarded native bit is outside
the original output dependency, and the complete residual outputs. Product
extraction and the surrounding composition remain explicit plan tasks.

## Ordered interfaces in AIG lowering

The ordinary CEC frontend writes AIGER with `-no-sort -symbols` and audits the
complete ordered input/output symbol lists against the declared RTL interface.
Some ABC engines compare positions, while others match names; matching names
as unordered sets is therefore insufficient. Missing, duplicated, reordered,
or incomplete symbols cause an interface error before invoking ABC. Never
promote a pass/fail disagreement between engines by selecting the pass.


### Native-gate ROBDD coefficient discharge

`cec.py --engine algebraic-terminal` also accepts
`--algebraic-coefficient-engine bdd`, `--algebraic-bdd-node-cap N`, and
`--algebraic-bdd-order bit-major` (or `port-major`). The default remains strict
coefficient CEC. The ROBDD backend evaluates the original primitive gate
functions directly and proves every reduced-width coefficient bit identically
zero. Complete independent residual replay and lossless grouping remain
mandatory. A node limit, unsupported signal, or nonzero coefficient returns
unknown; sampling is never a substitute. Bit-major ordering can help correlated
arithmetic inputs. Large node caps increase memory use and must be recorded.

The complete embedding plan accepts `coefficient_engine`, `bdd_node_cap`, and
`bdd_order` for the terminal route. For example, a proposed 23-bit embedding of
a 16-bit truncated word uses `low_bits: 7`; the checker preserves every original
gate, checks the exact high-bit connections, proves the full 23-bit word, and
strictly binds its projection to the retained 16-bit candidate. A projection
lemma alone does not prove other outputs of the original design.

Before AIG/BLIF lowering, the common checker rejects reachable X/Z or undriven
values in an output fanin. In particular, an auxiliary declaration such as
`wire po[2];` declares an unpacked array, not a scalar named `po[2]`; output
bit-select nodes must be renamed to valid, collision-free scalar wires. A malformed
auxiliary coefficient file must be rejected even if synthesis would replace its
undriven nodes with constants. Direct native-gate ROBDD evaluation avoids this
translation step; coefficient identities still need complete independent checks.
The two-state guard includes synthetic regressions for these malformed inputs.

For complete AIG primary-input case splits, see [aig_cases.md](aig_cases.md).
That checker can freshly run every branch or replay a pinned archive with fresh
independent cofactor identities. Its result concerns the supplied AIG pair;
complete original-RTL interface bridges must be proved separately.


## Portable release execution

All external tool selection is shared in `verify/tooling.py`: explicit flags,
then tool environment variables, optional CEC config, then PATH. A config's
relative executable paths use its own directory. SMT frontends query support
for `chformal -lower`: newer generalized `$check` cells are lowered when the
option exists; every result still requires the serialized assertion and complete
output-dependency audit. Missing proof duties remain errors, regardless of the
Yosys version or solver result.

Install only the Skill directory if desired. Terminal coefficient checking
locates `cec.py` beside the installed backend and passes through the selected
Yosys executable. Proof plans are hypotheses supplied by the agent, not automatic
cut or arithmetic discovery. Relative plan artifacts use the plan directory;
identity source paths use the identity directory. Never relocate historical
research proof records by deleting their source hashes or skipping validation.

# Exact native-terminal residual checking

From the Skill scripts directory:

```sh
python -m verify.algebraic_terminal \
  --reference /absolute/reference_primitive.v \
  --candidate /absolute/candidate_word.v \
  --coefficient-input operand_a \
  --out /absolute/new_proof_directory \
  --term-cap 300000 --timeout 180 --abc-timeout 60
```

Repeat `--coefficient-input` to select a union of complete original input ports. This is a search strategy, not an input restriction: all original primary inputs remain free. The current entry point supports a single complete output word and rejects case-split options. It accepts the conservative word-cell/interface subset of the checked algebraic frontend; unsupported arithmetic or port layouts return `unknown`.

The primary reducer retains long native cones whose entire original primary-input support lies in the selected domain. Short cones and local adder rewrites are eliminated algebraically modulo the declared output width. A separate scalar truth-table/subset-inversion implementation rechecks local identities and derives the same complete residual. A retained terminal always denotes its original native gate function; it is never assumed equal to a proposed arithmetic signal.

The residual is grouped losslessly by monomials in primary inputs outside the selected domain. Every remaining coefficient uses only native gates supported by the selected domain. The checker copies each coefficient's exact original gate closure into a separate RTL obligation, renames internal wires to avoid collisions, divides out the common power of two, and asks ordinary strict ABC CEC to prove every coefficient output bit zero. Every coefficient must pass. A nonzero coefficient can mean this sufficient decomposition failed, so rejection returns `unknown`, not a claim of a functional counterexample for the original pair.

A `pass` result requires independent residual replay, complete coefficient checking (or an independently replayed empty residual), unchanged input/source hashes, and complete coverage of the one original output word. No simulation result is accepted. The output directory retains the local identities, both residual derivations, coefficient construction and native-wire mapping, complete solver evidence, and copies/hashes of checker sources.

The Linux watchdog freezes and kills the entire descendant tree, including tool processes in their own sessions. A worker timeout, nonzero exit, unsupported interface, or incomplete stage cannot leave a stale `pass` result. Existing output directories are refused. The entry point does not create an embedding or alter a candidate: callers using an independently constructed auxiliary word must separately prove its complete projection/bridge back to the original retained candidate.

# Synthetic parity example

The function is `y = x[0] XOR x[1] XOR x[2]`. `reference.v` is a two-gate
implementation; `candidate.v` is reduction-XOR RTL; `incorrect.v` complements
the result and must fail verification. These files were authored for the demo,
not copied from a benchmark.

`parity.truth` lists the output for inputs 7, 6, ..., 0 in that order. The Skill
reader complements the table index to obtain ordinary Verilog input order.
Its eight-character string is `10010110`.

Run from the repository root:

```bash
python3 scripts/demo.py --out outputs/parity-demo
```

The demo is a deterministic installation/verification check. To exercise an LLM
recovery run, provide only `reference.v` to the agent, keep the candidate and
answer files out of its workspace, and use the prompt in the root README.

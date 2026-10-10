# PA-30 original input sources

The paper uses the 30 combinational primitive-gate Verilog inputs from
[ICCAD 2022 CAD Contest Problem A](https://www.iccad-contest.org/2022/Problems.html).
The official page provides the problem specification and benchmark downloads,
including the final [hidden-case archive](https://drive.google.com/file/d/1axlAw1rPXbTb_kYsvbwKshcEMF37SQWz/view).
All 30 primitive-gate files in that official archive were checked against the
final experiment hashes. `source.json` records the archive checksum and the
per-case identities. Use the official page for other distributions and updates.

The original input netlists are not redistributed here because an explicit
redistribution license has not been established. Source attribution does not
change the upstream terms. The recovered CREAS outputs are included separately
in `experiments/pa30-arithmetic/rtl/`.

Download and unpack the inputs from the official source, then arrange the
original gate-level files as:

```text
<pa30-inputs>/
  test01/top_primitive.v
  ...
  test30/top_primitive.v
```

The exact filenames and per-file SHA-256 values used in the final experiments
are recorded in `experiments/pa30-arithmetic/input_manifest.json`, under
`original_gate_input` and `original_gate_sha256`. Check all 30 files with:

```sh
python3 benchmarks/verify_inputs.py --pa30-dir /path/to/pa30-inputs
```

The synthesis and mapping runner also validates these input hashes. Its full
instructions are in `experiments/pa30-arithmetic/README.md`.

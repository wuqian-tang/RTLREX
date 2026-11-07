# PA-30 original benchmark inputs

The paper uses the 30 combinational primitive-gate Verilog inputs from
[ICCAD 2022 CAD Contest Problem A](https://www.iccad-contest.org/2022/Problems.html).
The official page provides the problem specification and benchmark downloads,
including the final [hidden-case archive](https://drive.google.com/file/d/1axlAw1rPXbTb_kYsvbwKshcEMF37SQWz/view).
All 30 primitive-gate files in that official archive were checked against the
final experiment hashes. `source.json` records the archive checksum and the
per-case identities. Use the official page for other distributions and updates.

All 30 original primitive-gate netlists are included unchanged under `inputs/`.
These are the exact input files used in the experiments, not recovered RTL or
contest reference answers. The recovered RTLREX outputs are included separately
in `experiments/pa30-arithmetic/rtl/`.

The contest makes these files publicly downloadable. No explicit redistribution
license has been identified in the reviewed source materials. They remain
third-party data and are **not covered by this repository's MIT license**.
Attribution and public availability do not establish an additional license.
See [NOTICE.md](NOTICE.md). The repository remains private while public
redistribution terms are unresolved.

The included layout is:

```text
benchmarks/pa30/inputs/
  test01/top_primitive.v
  ...
  test30/top_primitive.v
```

The exact filenames and per-file SHA-256 values used in the final experiments
are recorded in `experiments/pa30-arithmetic/input_manifest.json`, under
`original_gate_input` and `original_gate_sha256`. Check all 30 files with:

```sh
python3 benchmarks/verify_inputs.py --pa30-dir benchmarks/pa30/inputs
```

The same command accepts a separately downloaded input directory in place of
`benchmarks/pa30/inputs`. The synthesis and mapping runner also validates these input hashes. Its full
instructions are in `experiments/pa30-arithmetic/README.md`.

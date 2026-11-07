# Dependencies

The supported test platform is Linux, Python 3.10 or later. Some process
watchdogs inspect `/proc`; macOS and Windows are not validated platforms.
Use ordinary ASCII file and directory names without spaces, semicolons or other
tool-script delimiters. General quoting of arbitrary Yosys/ABC file names has
not been validated in this release.
The fast native sampler expects flattened netlists with separate port
declarations and named primitive instances. It is not a general Verilog
frontend. Use the Yosys/CEC routes for general supported RTL; empty or
undriven sampler output interfaces are rejected.

| Component | Used for |
| --- | --- |
| Python 3.10+ | Skill tools and regression suite |
| Yosys and yosys-smtbmc | RTL lowering, SAT, all-output SMT |
| Berkeley ABC | Combinational equivalence |
| Z3 command-line executable | SMT backend |
| Icarus Verilog (`iverilog`, `vvp`) | Simulation and exhaustive truth replay |
| `g++`, C++17 | Compile the native primitive sampler on first use |
| NumPy | Optional truth-table recognition/acceleration |

For a recent binary toolchain, use
[YosysHQ OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build), following
its extraction and environment instructions. The GitHub workflow pins the
`2026-09-12` suite release. That CI environment is separate from the locally
tested environment; check the repository's Actions tab for the result of a
specific commit instead of treating a workflow file as proof that CI passed.

Distribution packages are another option. On Ubuntu/Debian, the usual package
names are `yosys berkeley-abc iverilog z3 g++ python3-venv`. Distribution versions
can lag behind current Yosys. Run the full suite, including SMT negative
controls, with the versions you select. No minimum Yosys version is claimed
solely from the presence of its executable.

The source environment used for release validation has Python 3.10.12, NumPy
2.2.6, Yosys 0.63+161 (commit `5fd39ff3e`), and Berkeley ABC 1.01. Exact local
validation results are recorded with the release review.

Verification tool selection supports explicit CLI paths, environment variables
`YOSYS`, `ABC`, `YOSYS_SMTBMC`, `IVERILOG`, `VVP`, and `CXX`, an optional
local `scripts/tool_paths.env` where supported, and ordinary `PATH` discovery.
The dependency doctor uses the same executable resolver for these variables. ABC may be named `abc`, `berkeley-abc` or `yosys-abc`.
Place `z3` in `PATH` for the SMT driver. Icarus and the compiler can also be
configured using the overrides above. Local tool configuration is
ignored by Git; executable files are not bundled.

```bash
python3 scripts/doctor.py --require-all
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The installer only copies the Skill. It does not install system packages,
change credentials, call model APIs or configure a paid service. Normal Python
assertions must remain enabled; do not use `python -O` or `PYTHONOPTIMIZE`.

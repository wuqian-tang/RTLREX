# Synthetic regression tests

From the release root:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The full suite requires Python 3.10+, Yosys, ABC, `yosys-smtbmc`, Z3, and `g++`.
Install executables on `PATH`, or use the tool environment overrides described
in the root README. A missing required executable fails the full suite; it is
not silently reported as a successful skipped proof.

All RTL, AIG, polynomial, and SMT fixtures here are synthetic. Tests create
their proof plans and artifacts in temporary directories. No contest circuits,
retained research outputs, API calls, or archived benchmark certificates are
required. The proof-duty audit uses an explicit synthetic SMT serialization.

Coverage includes fresh strict ABC and SMT equivalence with a changed final
output as the negative control; native-gate ROBDD identities and incorrect
coefficients; algebraic, sliced, signed, and terminal proofs; complete cofactor
covers; typed low-prefix products; full-output SAT; and source/interface,
unknown-value, timeout, forged-artifact, and missing-coverage rejection.
Tests of parser logic use controlled synthetic solver text, and watchdog
tests use short local subprocesses. These do not replace the fresh solver tests.

Some discoverable tests run several related adversarial checks within one
test method. A test count therefore counts test methods, not benchmarks or
independent circuit recoveries. Passing this suite is not a claim that an LLM
automatically discovers every proof plan or that all possible RTL is supported.

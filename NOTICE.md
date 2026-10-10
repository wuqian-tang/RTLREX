# Sources and third-party components

The Python cost calculator is the project's implementation of a syntax metric;
it is not an official ICCAD contest evaluation program. The shipped
`skills/circuit-reverse-rtl/scripts/cost/syntax_cost.csv` is a custom study
profile based on the **ICCAD 2022 CAD Contest, Problem A**, specification,
Appendices A and B. Its differences include changed operator weights and
additional zero-cost keywords. See the
[official contest problem page](https://www.iccad-contest.org/2022/Problems.html)
for the original specification and distribution terms. The default CSV is not
an official IWLS metric either.

No contest specification PDF, benchmark netlist, truth-table dataset, golden
answer, standard-cell library, Yosys source, ABC source or solver executable is
redistributed here. External software remains subject to its own license:

- [Yosys](https://github.com/YosysHQ/yosys): ISC license.
- [Berkeley ABC](https://github.com/berkeley-abc/abc): upstream copyright terms.
- [Z3](https://github.com/Z3Prover/z3): MIT license.
- [Icarus Verilog](https://github.com/steveicarus/iverilog): upstream GPL terms.
- [NumPy](https://github.com/numpy/numpy): BSD license.
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA): upstream GPL terms.
- [Nangate45 library distribution](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/tree/master/flow/platforms/nangate45):
  original library and platform terms, provided by upstream. The synthesis
  artifact records the source revision and hashes and does not bundle the library.

The parity example and regression fixtures are synthetic. Experiment CSV/JSON
files report this project's measurements. Included recovered RTL is the
project's output, rather than a contest reference answer. The project's code
and documentation are distributed under the MIT License in `LICENSE`.
This license does not relicense external data or tools; their original terms
and required notices continue to apply.

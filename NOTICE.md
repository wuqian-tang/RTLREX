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

The parity example and regression fixtures are synthetic. The project's code
and documentation are distributed under the MIT License in `LICENSE`.
This license does not relicense external data or tools; their original terms
and required notices continue to apply.

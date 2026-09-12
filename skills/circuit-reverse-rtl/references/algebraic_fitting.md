# Algebraic Fitting

Use this reference for Boolean or coefficient-solving subproblems.

## GF(2) Boolean Fitting

Use `algebra.gf2` from the skill scripts instead of rewriting Gaussian elimination. Set `PYTHONPATH=skills/circuit-reverse-rtl/scripts` when importing it from ad hoc Python.

```python
from algebra.gf2 import fit_bits, formula_expression, monomial_terms

terms = monomial_terms(["a", "b", "c"], max_degree=2)
coeffs = fit_bits(samples, output_bits, terms)
expr = formula_expression(coeffs, terms)
```

Validate on fresh samples. Low-degree ANF fits can overfit if controls are sparse or if the sampled support does not include boundary cases.

## Modular Arithmetic Fitting

For wrapped word outputs, track the arithmetic domain:

- `2^n` modular rings are not fields; do not assume ordinary Gaussian elimination works for arbitrary coefficients.
- If coefficients are expected to be small, search small signed coefficients over candidate terms and validate on independent vectors.
- For odd-prime moduli or GF(2) bit equations, use field solvers.

## Sampling Guidance

Use zero, all-ones, MSB-only, alternating bits, one-hot, paired controls, and random vectors. Refresh with a different seed before running formal CEC.

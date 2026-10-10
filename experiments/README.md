# Final experiment artifacts

| Package | Included data | Reproduction |
| --- | --- | --- |
| [PA-30 arithmetic-aware synthesis](pa30-arithmetic/README.md) | All 30 per-case area and delay measurements, retained RTL, source and tool hashes | Recompute paired means without EDA tools, or rerun synthesis and mapping with separately obtained inputs and library |
| [TT-100 final comparison](tt100-final/README.md) | Final per-case validation, representation, cost and runtime records | Recompute coverage and same-case cost comparisons without generating new RTL |

The PA-30 study shows how recovered high-level arithmetic can help subsequent
synthesis and technology mapping. Its uniform arithmetic-aware profile reduces
mean cell area by 1.75% and mean delay by 3.03% over the same 29 completed pairs.
Individual circuits retain area–delay tradeoffs. The original test22 mapping
times out and is excluded from both paired means.

The packages preserve final measurements and their provenance. The [original TT-100 truth tables](../benchmarks/tt100/README.md) are included
separately under `benchmarks/tt100/`, with upstream license and attribution.
[PA-30 input sources](../benchmarks/pa30/README.md) are documented for separate
acquisition. Reference RTL answers are not included. Consult each
package for exact input requirements and verification scope.

"""Read IWLS/ABC-style .truth files.

The IWLS truth files used with ABC ``read_truth -xf`` store rows in
complemented input-index order.  The helpers below expose values in normal
Verilog input order: ``words[x]`` is the packed output for ``top(.x(x))``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple


def read_truth_lines(path: str | Path) -> List[str]:
    truth_path = Path(path)
    lines = [line.strip() for line in truth_path.read_text().splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{truth_path}: empty truth file")
    width = len(lines[0])
    if width == 0 or width & (width - 1):
        raise ValueError(f"{truth_path}: row length {width} is not a power of two")
    for idx, line in enumerate(lines, 1):
        if len(line) != width:
            raise ValueError(f"{truth_path}: row {idx} has length {len(line)}, expected {width}")
        bad = set(line) - {"0", "1"}
        if bad:
            raise ValueError(f"{truth_path}: row {idx} contains non-binary characters")
    return lines


def read_truth_words(path: str | Path, complemented_index: bool = True) -> Tuple[int, int, List[int]]:
    """Return ``(n_inputs, n_outputs, words)`` in normal Verilog input order."""

    lines = read_truth_lines(path)
    n_out = len(lines)
    n_entries = len(lines[0])
    n_in = int(math.log2(n_entries))
    mask = n_entries - 1
    words = [0] * n_entries
    for input_value in range(n_entries):
        truth_idx = (~input_value) & mask if complemented_index else input_value
        word = 0
        for bit_idx, line in enumerate(lines):
            if line[truth_idx] == "1":
                word |= 1 << bit_idx
        words[input_value] = word
    return n_in, n_out, words


def words_to_bit_tables(words: List[int], n_out: int) -> List[List[int]]:
    return [[(word >> bit_idx) & 1 for word in words] for bit_idx in range(n_out)]

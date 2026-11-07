"""Stable source-cost selection; exact verification remains the caller's job."""
from pathlib import Path
from tempfile import TemporaryDirectory

from cost.RTL_cost_calculator import evaluate_rtl


def lowest_cost_source(sources):
    candidates = tuple(dict.fromkeys(sources))
    if not candidates:
        raise ValueError('at least one RTL candidate is required')
    if len(candidates) == 1:
        return candidates[0]
    with TemporaryDirectory(prefix='rtl-cost-candidates-') as temporary:
        path = Path(temporary) / 'candidate.v'
        prices = []
        for source in candidates:
            path.write_text(source)
            prices.append(evaluate_rtl(str(path))[0])
    return candidates[min(range(len(prices)), key=prices.__getitem__)]

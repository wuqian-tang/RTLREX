"""Verification requires active invariant checks, including Python assertions."""

if not __debug__:
    raise RuntimeError(
        "Verification requires Python assertions enabled; do not use python -O, "
        "python -OO, or PYTHONOPTIMIZE."
    )

"""External executable lookup for the synthetic regression suite."""
import os
from pathlib import Path
import shutil


def tool_path(name):
    override = os.environ.get(name.upper())
    choices = [override] if override else [name]
    if name == "abc" and not override:
        choices = ["abc", "berkeley-abc", "yosys-abc"]
    for choice in choices:
        resolved = shutil.which(choice)
        if resolved:
            return Path(resolved)
    raise RuntimeError(f"Required tool {name!r} unavailable; install it on PATH or set {name.upper()}")

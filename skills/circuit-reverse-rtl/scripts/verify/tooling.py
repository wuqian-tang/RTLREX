"""Portable executable and artifact discovery; no research-checkout defaults."""
import os
import shutil
from pathlib import Path

TOOLS = {"YOSYS": ("yosys",), "ABC": ("abc", "yosys-abc", "berkeley-abc"),
         "YOSYS_SMTBMC": ("yosys-smtbmc",), "IVERILOG": ("iverilog",),
         "VVP": ("vvp",), "CXX": ("g++", "clang++")}

def executable(value, label="tool", base_dir=None):
    value = os.fspath(value)
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or "/" in value:
        candidate = (candidate if candidate.is_absolute() else Path(base_dir or Path.cwd()) / candidate).absolute()
    else:
        found = shutil.which(value)
        if not found:
            raise ValueError(f"{label} executable not found in PATH: {value}")
        candidate = Path(found).absolute()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise ValueError(f"{label} executable is missing or not executable: {candidate}")
    # Keep symlink names: tools may use argv[0] or sibling data directories.
    return candidate.absolute()

def resolve_tool(name, explicit=None, config=None, config_path=None):
    """Explicit flag > environment > optional legacy config > PATH.

    A configured but invalid executable is an error, never a silent fallback.
    Relative config paths are based at the config file; other paths use cwd.
    """
    if explicit is not None:
        return executable(explicit, name)
    if os.environ.get(name):
        return executable(os.environ[name], name)
    if config and config.get(name):
        return executable(config[name], name, Path(config_path).absolute().parent if config_path else None)
    for command in TOOLS.get(name, (name.lower(),)):
        if shutil.which(command):
            return executable(command, name)
    raise ValueError(f"{name} unavailable; install it on PATH, set {name}, or pass its executable flag")

def optional_tool(name):
    try:
        return str(resolve_tool(name))
    except ValueError:
        return None

def artifact_path(value, base_dir=None):
    """Relative artifact names use an explicit manifest directory, else cwd."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(base_dir or Path.cwd()) / path).resolve()


def load_plan(path):
    """Load a JSON plan; artifact records are relative to this file's directory.

    Resolve only {path, sha256} records, preserving values and proof statements.
    Generated plans/records therefore retain absolute artifact locations.
    """
    import json
    path = Path(path).resolve()
    def visit(value):
        if isinstance(value, dict):
            result = {k: visit(v) for k, v in value.items()}
            if isinstance(result.get("path"), str) and "sha256" in result:
                result["path"] = str(artifact_path(result["path"], path.parent))
            return result
        if isinstance(value, list):
            return [visit(v) for v in value]
        return value
    return visit(json.loads(path.read_text()))

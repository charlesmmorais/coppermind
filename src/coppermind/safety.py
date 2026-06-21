"""Path validation for tool inputs/outputs.

Tools that touch the filesystem (importing a SES, pointing at a DSN/jar) take
paths from the model. These helpers resolve `~`, follow symlinks, and enforce an
expected extension, so a tool fails fast and clearly instead of opening or
writing somewhere unexpected. Pure logic over the filesystem — easy to unit-test.
"""

from __future__ import annotations

from pathlib import Path


def validate_input_file(path: str, suffixes: set[str] | None = None) -> str:
    """Resolve and validate an existing input file; return its absolute path.

    Raises FileNotFoundError if missing, ValueError if it is not a regular file
    or its extension is not in ``suffixes`` (when given).
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"file not found: {path}")
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {path}")
    if suffixes and resolved.suffix.lower() not in {s.lower() for s in suffixes}:
        raise ValueError(f"expected one of {sorted(suffixes)} but got '{resolved.suffix}': {path}")
    return str(resolved)


def validate_output_path(path: str, suffixes: set[str] | None = None) -> str:
    """Resolve and validate a writable output path; return its absolute path.

    The parent directory must already exist. Validates the extension when given.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.parent.exists():
        raise FileNotFoundError(f"output directory does not exist: {resolved.parent}")
    if suffixes and resolved.suffix.lower() not in {s.lower() for s in suffixes}:
        raise ValueError(f"expected one of {sorted(suffixes)} but got '{resolved.suffix}': {path}")
    return str(resolved)

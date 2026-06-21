"""Persist a Coppermind Board to/from JSON.

Lets a project be saved and resumed across sessions, independent of KiCAD. The
board is a pydantic model, so this is a thin, lossless round-trip over
``model_dump_json`` / ``model_validate_json`` with light path validation.
"""

from __future__ import annotations

from pathlib import Path

from coppermind.domain.models import Board


def save_board(board: Board, path: str, *, indent: int = 2) -> str:
    """Write a board to a .json file; returns the absolute path."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.parent.exists():
        raise FileNotFoundError(f"output directory does not exist: {resolved.parent}")
    resolved.write_text(board.model_dump_json(indent=indent), encoding="utf-8")
    return str(resolved)


def load_board(path: str) -> Board:
    """Load a board previously written by ``save_board``."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"board file not found: {path}")
    return Board.model_validate_json(resolved.read_text(encoding="utf-8"))

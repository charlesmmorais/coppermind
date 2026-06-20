"""Explain mode — turn board state + advice into a human narrative.

Collaboration is not just doing the edit; it's explaining *why*. This composes a
plain-language account of the current board and the active design advice, each
point carrying its citation, so the user can follow (and learn from) the
copilot's reasoning.
"""

from __future__ import annotations

from coppermind.domain.models import Board
from coppermind.intelligence.critique import critique


def explain_board(board: Board, assumed_current_a: float = 0.5) -> dict:
    """Return a structured explanation: summary, narrative lines, cited advice."""
    findings = critique(board, assumed_current_a=assumed_current_a)
    outline = board.outline
    summary = {
        "name": board.name,
        "size_mm": f"{outline.width}x{outline.height}" if outline else None,
        "components": len(board.components),
        "nets": len(board.nets),
        "tracks": len(board.tracks),
        "advice_count": len(findings),
    }

    lines: list[str] = []
    size = summary["size_mm"] or "no outline"
    lines.append(
        f"Board '{board.name}' ({size}): {summary['components']} components, "
        f"{summary['nets']} nets, {summary['tracks']} tracks."
    )
    if not findings:
        lines.append("No design-rule advice — the board passes the current knowledge base.")
    else:
        lines.append(f"{len(findings)} advisory point(s) from the EE knowledge base:")
        for f in findings:
            where = f" at {f.where}" if f.where else ""
            lines.append(f"- {f.message}{where}. Why: {f.rule}. Fix: {f.suggestion}")

    return {
        "summary": summary,
        "narrative": "\n".join(lines),
        "advice": [f.model_dump() for f in findings],
    }

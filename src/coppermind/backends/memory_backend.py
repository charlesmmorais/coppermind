"""In-memory backend.

Stores the board in a dict — no KiCAD required. This is what makes the entire
domain + transaction + verification stack testable in CI without launching
KiCAD, and it doubles as a fast dev/offline mode. It also renders a tiny SVG so
the visual-feedback path can be exercised end to end.
"""

from __future__ import annotations

from coppermind.backends.base import KicadBackend
from coppermind.domain.models import Board, BoardOutline


class MemoryBackend(KicadBackend):
    name = "memory"

    def __init__(self) -> None:
        self._store: dict[str, Board] = {}

    def is_available(self) -> bool:
        return True

    def load(self, name: str) -> Board:
        if name not in self._store:
            self._store[name] = Board(name=name)
        return self._store[name].copy_deep()

    def apply(self, board: Board) -> None:
        self._store[board.name] = board.copy_deep()

    def render(self, board: Board) -> bytes | None:
        outline = board.outline or BoardOutline(width=10, height=10)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {outline.width} {outline.height}">',
            f'<rect x="0" y="0" width="{outline.width}" height="{outline.height}" '
            f'fill="#0b3d2e" stroke="#d4a017" stroke-width="0.2"/>',
        ]
        for t in board.tracks:
            parts.append(
                f'<line x1="{t.start.x}" y1="{t.start.y}" x2="{t.end.x}" y2="{t.end.y}" '
                f'stroke="#c87137" stroke-width="{t.width}"/>'
            )
        for comp in board.components.values():
            parts.append(
                f'<rect x="{comp.position.x - comp.half_size.x}" '
                f'y="{comp.position.y - comp.half_size.y}" '
                f'width="{comp.half_size.x * 2}" height="{comp.half_size.y * 2}" '
                f'fill="#222" stroke="#eee" stroke-width="0.1"/>'
            )
        parts.append("</svg>")
        return "".join(parts).encode("utf-8")

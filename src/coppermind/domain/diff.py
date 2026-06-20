"""Structured diff between two board states.

The diff is what powers `design_preview`: the user (or the AI) sees exactly what
a transaction will change before it is committed. Output is plain data so it can
be rendered as text, JSON, or a visual overlay.
"""

from __future__ import annotations

from pydantic import BaseModel

from coppermind.domain.models import Board


class BoardDiff(BaseModel):
    components_added: list[str] = []
    components_removed: list[str] = []
    components_modified: list[str] = []
    nets_added: list[str] = []
    nets_removed: list[str] = []
    tracks_added: int = 0
    tracks_removed: int = 0
    vias_added: int = 0
    vias_removed: int = 0

    @property
    def is_empty(self) -> bool:
        return not (
            self.components_added
            or self.components_removed
            or self.components_modified
            or self.nets_added
            or self.nets_removed
            or self.tracks_added
            or self.tracks_removed
            or self.vias_added
            or self.vias_removed
        )

    def summary(self) -> str:
        if self.is_empty:
            return "No changes."
        parts: list[str] = []
        if self.components_added:
            parts.append(f"+{len(self.components_added)} components ({', '.join(self.components_added)})")
        if self.components_modified:
            parts.append(f"~{len(self.components_modified)} components ({', '.join(self.components_modified)})")
        if self.components_removed:
            parts.append(f"-{len(self.components_removed)} components ({', '.join(self.components_removed)})")
        if self.nets_added:
            parts.append(f"+{len(self.nets_added)} nets ({', '.join(self.nets_added)})")
        if self.nets_removed:
            parts.append(f"-{len(self.nets_removed)} nets")
        if self.tracks_added:
            parts.append(f"+{self.tracks_added} tracks")
        if self.tracks_removed:
            parts.append(f"-{self.tracks_removed} tracks")
        if self.vias_added:
            parts.append(f"+{self.vias_added} vias")
        if self.vias_removed:
            parts.append(f"-{self.vias_removed} vias")
        return "; ".join(parts)


def diff_boards(before: Board, after: Board) -> BoardDiff:
    """Compute the structured difference `after - before`."""
    before_refs = set(before.components)
    after_refs = set(after.components)

    modified = sorted(
        ref
        for ref in before_refs & after_refs
        if before.components[ref] != after.components[ref]
    )

    return BoardDiff(
        components_added=sorted(after_refs - before_refs),
        components_removed=sorted(before_refs - after_refs),
        components_modified=modified,
        nets_added=sorted(set(after.nets) - set(before.nets)),
        nets_removed=sorted(set(before.nets) - set(after.nets)),
        tracks_added=max(0, len(after.tracks) - len(before.tracks)),
        tracks_removed=max(0, len(before.tracks) - len(after.tracks)),
        vias_added=max(0, len(after.vias) - len(before.vias)),
        vias_removed=max(0, len(before.vias) - len(after.vias)),
    )

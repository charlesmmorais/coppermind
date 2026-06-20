"""Pure translation from a Board diff into an IPC apply plan.

This module deliberately does NOT import kipy. It decides *what* must change on
the live KiCAD board; the IPCBackend then performs the kipy/commit calls
(create_items / update_items / remove_items). Keeping the decision logic pure
makes it unit-testable without KiCAD and keeps the adapter thin.

Phase 2 adds in-place edits: components that exist in both boards but changed
(moved / re-valued / re-footprinted) become *modifications* rather than
add+remove, and individual track changes are detected positionally.
"""

from __future__ import annotations

from pydantic import BaseModel

from coppermind.domain.models import Board, Component, Track, Via


class ApplyPlan(BaseModel):
    """An ordered description of changes to push to the live board."""

    nets_to_create: list[str] = []
    footprints_to_add: list[Component] = []
    components_to_modify: list[Component] = []          # after-state of changed comps
    component_refs_to_remove: list[str] = []
    tracks_to_add: list[Track] = []
    tracks_to_modify: list[tuple[int, Track]] = []      # (index, after-state)
    track_indices_to_remove: list[int] = []
    vias_to_add: list[Via] = []
    via_indices_to_remove: list[int] = []

    @property
    def is_empty(self) -> bool:
        return not (
            self.nets_to_create
            or self.footprints_to_add
            or self.components_to_modify
            or self.component_refs_to_remove
            or self.tracks_to_add
            or self.tracks_to_modify
            or self.track_indices_to_remove
            or self.vias_to_add
            or self.via_indices_to_remove
        )


def plan_apply(before: Board, after: Board) -> ApplyPlan:
    """Compute the incremental plan to turn `before` into `after` on the board.

    Nets are listed first because tracks/footprints reference them. Components
    present in both boards but unequal become modifications (covers moves and
    field edits). Tracks are compared positionally: the shared prefix yields
    modifications, the tail yields additions or removals.
    """
    nets_to_create = [n for n in after.nets if n not in before.nets]

    footprints_to_add = [
        comp for ref, comp in after.components.items() if ref not in before.components
    ]
    component_refs_to_remove = [ref for ref in before.components if ref not in after.components]
    components_to_modify = [
        comp
        for ref, comp in after.components.items()
        if ref in before.components and before.components[ref] != comp
    ]

    shared = min(len(before.tracks), len(after.tracks))
    tracks_to_modify = [
        (i, after.tracks[i]) for i in range(shared) if before.tracks[i] != after.tracks[i]
    ]
    tracks_to_add = list(after.tracks[len(before.tracks):]) if len(after.tracks) > len(before.tracks) else []
    track_indices_to_remove = (
        list(range(len(after.tracks), len(before.tracks)))
        if len(before.tracks) > len(after.tracks)
        else []
    )

    vias_to_add = list(after.vias[len(before.vias):]) if len(after.vias) > len(before.vias) else []
    via_indices_to_remove = (
        list(range(len(after.vias), len(before.vias)))
        if len(before.vias) > len(after.vias)
        else []
    )

    return ApplyPlan(
        nets_to_create=nets_to_create,
        footprints_to_add=footprints_to_add,
        components_to_modify=components_to_modify,
        component_refs_to_remove=component_refs_to_remove,
        tracks_to_add=tracks_to_add,
        tracks_to_modify=tracks_to_modify,
        track_indices_to_remove=track_indices_to_remove,
        vias_to_add=vias_to_add,
        via_indices_to_remove=via_indices_to_remove,
    )

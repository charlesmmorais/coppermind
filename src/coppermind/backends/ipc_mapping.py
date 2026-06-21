"""Pure translation from a Board diff into an IPC apply plan.

This module deliberately does NOT import kipy. It decides *what* must change on
the live KiCAD board; the IPCBackend then performs the kipy/commit calls
(create_items / update_items / remove_items). Keeping the decision logic pure
makes it unit-testable without KiCAD and keeps the adapter thin.

Tracks and vias are matched by **stable id** (not by list position), so the diff
is correct even when items are reordered or inserted in the middle. Components
are matched by their reference (their natural key). Items present in both boards
but with different content become *modifications*.
"""

from __future__ import annotations

from pydantic import BaseModel

from coppermind.domain.models import Board, Component, Track, Via, content_without_id


class ApplyPlan(BaseModel):
    """An ordered description of changes to push to the live board."""

    nets_to_create: list[str] = []
    footprints_to_add: list[Component] = []
    components_to_modify: list[Component] = []      # after-state of changed comps
    component_refs_to_remove: list[str] = []
    tracks_to_add: list[Track] = []
    tracks_to_modify: list[Track] = []              # after-state, carries stable id
    track_ids_to_remove: list[str] = []
    vias_to_add: list[Via] = []
    vias_to_modify: list[Via] = []                  # after-state, carries stable id
    via_ids_to_remove: list[str] = []

    @property
    def is_empty(self) -> bool:
        return not (
            self.nets_to_create
            or self.footprints_to_add
            or self.components_to_modify
            or self.component_refs_to_remove
            or self.tracks_to_add
            or self.tracks_to_modify
            or self.track_ids_to_remove
            or self.vias_to_add
            or self.vias_to_modify
            or self.via_ids_to_remove
        )


def _diff_by_id(before: list, after: list) -> tuple[list, list, list[str]]:
    """Return (to_add, to_modify, ids_to_remove) matching items by their .id."""
    bx = {it.id: it for it in before}
    ax = {it.id: it for it in after}
    to_add = [it for iid, it in ax.items() if iid not in bx]
    ids_to_remove = [iid for iid in bx if iid not in ax]
    to_modify = [
        it
        for iid, it in ax.items()
        if iid in bx and content_without_id(bx[iid]) != content_without_id(it)
    ]
    return to_add, to_modify, ids_to_remove


def plan_apply(before: Board, after: Board) -> ApplyPlan:
    """Compute the incremental plan to turn `before` into `after` on the board."""
    nets_to_create = [n for n in after.nets if n not in before.nets]

    footprints_to_add = [
        comp for ref, comp in after.components.items() if ref not in before.components
    ]
    component_refs_to_remove = [ref for ref in before.components if ref not in after.components]
    components_to_modify = [
        comp
        for ref, comp in after.components.items()
        if ref in before.components
        and content_without_id(before.components[ref]) != content_without_id(comp)
    ]

    tracks_to_add, tracks_to_modify, track_ids_to_remove = _diff_by_id(
        before.tracks, after.tracks
    )
    vias_to_add, vias_to_modify, via_ids_to_remove = _diff_by_id(before.vias, after.vias)

    return ApplyPlan(
        nets_to_create=nets_to_create,
        footprints_to_add=footprints_to_add,
        components_to_modify=components_to_modify,
        component_refs_to_remove=component_refs_to_remove,
        tracks_to_add=tracks_to_add,
        tracks_to_modify=tracks_to_modify,
        track_ids_to_remove=track_ids_to_remove,
        vias_to_add=vias_to_add,
        vias_to_modify=vias_to_modify,
        via_ids_to_remove=via_ids_to_remove,
    )

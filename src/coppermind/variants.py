"""Design variants (a KiCAD 10 feature), KiCAD-independent.

A variant is a named set of per-component overrides applied to a base board:
change a value or footprint, or mark a part Do-Not-Populate (DNP). Resolving a
variant yields a new Board — DNP parts are dropped — so the same base design can
produce multiple assembled configurations (BOM/fab) without forking the project.
"""

from __future__ import annotations

from pydantic import BaseModel

from coppermind.domain.models import Board


class ComponentOverride(BaseModel):
    value: str | None = None
    footprint: str | None = None
    dnp: bool = False


class Variant(BaseModel):
    name: str
    overrides: dict[str, ComponentOverride] = {}


def resolve_variant(board: Board, variant: Variant) -> Board:
    """Return a new Board with the variant applied (DNP components removed)."""
    result = board.copy_deep()
    for ref, ov in variant.overrides.items():
        if ref not in result.components:
            continue
        if ov.dnp:
            del result.components[ref]
            continue
        updates: dict[str, object] = {}
        if ov.value is not None:
            updates["value"] = ov.value
        if ov.footprint is not None:
            updates["footprint"] = ov.footprint
        if updates:
            result.components[ref] = result.components[ref].model_copy(update=updates)
    return result

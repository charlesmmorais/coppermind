from __future__ import annotations

import pytest

from coppermind.schematic.incremental import (
    _foreign_wire_contact_is_blocking,
    _route_collides,
    _route_incremental_geometry,
    _segments_intersect,
)
from coppermind.schematic.models import Wire


def _wire(x1: float, y1: float, x2: float, y2: float, net: str) -> Wire:
    return Wire(x1=x1, y1=y1, x2=x2, y2=y2, net=net)


def test_clean_perpendicular_interior_crossing_is_allowed() -> None:
    horizontal = _wire(0.0, 10.16, 20.32, 10.16, "A")
    vertical = _wire(10.16, 0.0, 10.16, 20.32, "B")

    assert _segments_intersect(horizontal, vertical) is True
    assert _foreign_wire_contact_is_blocking(horizontal, vertical) is False
    assert _route_collides([horizontal], [vertical]) is False


def test_router_prefers_direct_route_through_safe_crossing() -> None:
    foreign = _wire(10.16, 0.0, 10.16, 20.32, "B")
    wires, _label, junctions = _route_incremental_geometry(
        "A",
        [(0.0, 10.16), (20.32, 10.16)],
        [foreign],
    )

    total_length = sum(abs(wire.x2 - wire.x1) + abs(wire.y2 - wire.y1) for wire in wires)
    assert total_length == pytest.approx(20.32)
    assert junctions == []
    assert any(_segments_intersect(wire, foreign) for wire in wires)


def test_t_or_endpoint_contact_remains_blocking() -> None:
    ending_wire = _wire(0.0, 10.16, 10.16, 10.16, "A")
    through_wire = _wire(10.16, 0.0, 10.16, 20.32, "B")

    assert _foreign_wire_contact_is_blocking(ending_wire, through_wire) is True
    assert _route_collides([ending_wire], [through_wire]) is True


def test_collinear_overlap_remains_blocking() -> None:
    left = _wire(0.0, 10.16, 20.32, 10.16, "A")
    right = _wire(10.16, 10.16, 30.48, 10.16, "B")

    assert _foreign_wire_contact_is_blocking(left, right) is True
    assert _route_collides([left], [right]) is True


def test_crossing_at_protected_pin_or_junction_point_is_blocking() -> None:
    horizontal = _wire(0.0, 10.16, 20.32, 10.16, "A")
    vertical = _wire(10.16, 0.0, 10.16, 20.32, "B")

    # The crossing is geometrically safe only while it has no electrical point.
    assert _route_collides(
        [horizontal],
        [vertical],
        foreign_points=[(10.16, 10.16)],
    ) is True

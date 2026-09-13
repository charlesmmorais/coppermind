"""Incremental schematic construction without whole-sheet reflow.

This module is the geometry counterpart to stepwise Circuit IR authoring.  It
keeps already placed symbols where they are, places new symbols relative to an
existing anchor, and reroutes only the net that changed.
"""

from __future__ import annotations

import math
from pathlib import Path

from coppermind.circuit import Circuit
from coppermind.libraries import SymbolResolver
from coppermind.safety import validate_output_path
from coppermind.schematic.composer import (
    _net_has_named_power_symbol,
    _pin_anchor,
)
from coppermind.schematic.erc import run_kicad_erc
from coppermind.schematic.models import Junction, NetLabel, Schematic, Wire
from coppermind.serialize.kicad_sch import schematic_to_kicad_sch

_GRID = 2.54
_MAX_RELATIVE_GAP = 101.6
_DIRECTIONS = {
    "right": (1.0, 0.0),
    "left": (-1.0, 0.0),
    "above": (0.0, -1.0),
    "below": (0.0, 1.0),
}
_BLOCKING_SEVERITIES = {"error", "fatal"}
_EPS = 1e-6


def _snap(value: float) -> float:
    return round(value / _GRID) * _GRID


def _coord(value: float) -> float:
    return round(float(value), 6)


def _symbol_by_ref(schematic: Schematic, reference: str):
    return next((item for item in schematic.symbols if item.reference == reference), None)


def place_relative_geometry(
    schematic: Schematic,
    reference: str,
    anchor: str,
    direction: str = "right",
    gap_mm: float = 25.4,
) -> dict:
    """Move one symbol relative to another without touching existing geometry."""
    if reference == anchor:
        raise ValueError("reference and anchor must be different components")
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(_DIRECTIONS)}")
    if not math.isfinite(gap_mm) or gap_mm < _GRID or gap_mm > _MAX_RELATIVE_GAP:
        raise ValueError(f"gap_mm must be between {_GRID} and {_MAX_RELATIVE_GAP}")

    target = _symbol_by_ref(schematic, reference)
    anchor_symbol = _symbol_by_ref(schematic, anchor)
    if target is None:
        raise KeyError(f"component '{reference}' has no drawable symbol")
    if anchor_symbol is None:
        raise KeyError(f"anchor component '{anchor}' has no drawable symbol")

    dx, dy = _DIRECTIONS[direction]
    old = (target.x, target.y)
    target.x = _snap(anchor_symbol.x + dx * gap_mm)
    target.y = _snap(anchor_symbol.y + dy * gap_mm)
    return {
        "reference": reference,
        "anchor": anchor,
        "direction": direction,
        "gap_mm": gap_mm,
        "from": {"x": old[0], "y": old[1]},
        "to": {"x": target.x, "y": target.y},
    }


def _wire_key(wire: Wire) -> tuple[tuple[float, float], tuple[float, float]]:
    a = (_coord(wire.x1), _coord(wire.y1))
    b = (_coord(wire.x2), _coord(wire.y2))
    return tuple(sorted((a, b)))  # type: ignore[return-value]


def _append_wire(
    target: list[Wire],
    seen: set[tuple[tuple[float, float], tuple[float, float]]],
    a: tuple[float, float],
    b: tuple[float, float],
    net_name: str,
) -> None:
    a = (_coord(a[0]), _coord(a[1]))
    b = (_coord(b[0]), _coord(b[1]))
    if a == b:
        return
    wire = Wire(x1=a[0], y1=a[1], x2=b[0], y2=b[1], net=net_name)
    key = _wire_key(wire)
    if key not in seen:
        target.append(wire)
        seen.add(key)


def _between(value: float, a: float, b: float) -> bool:
    return min(a, b) - _EPS <= value <= max(a, b) + _EPS


def _segments_intersect(left: Wire, right: Wire) -> bool:
    """Return whether two axis-aligned wire segments touch or overlap."""
    left_vertical = math.isclose(left.x1, left.x2, abs_tol=_EPS)
    right_vertical = math.isclose(right.x1, right.x2, abs_tol=_EPS)

    if left_vertical and right_vertical:
        if not math.isclose(left.x1, right.x1, abs_tol=_EPS):
            return False
        return max(min(left.y1, left.y2), min(right.y1, right.y2)) <= min(
            max(left.y1, left.y2), max(right.y1, right.y2)
        ) + _EPS

    if not left_vertical and not right_vertical:
        if not math.isclose(left.y1, right.y1, abs_tol=_EPS):
            return False
        return max(min(left.x1, left.x2), min(right.x1, right.x2)) <= min(
            max(left.x1, left.x2), max(right.x1, right.x2)
        ) + _EPS

    vertical, horizontal = (left, right) if left_vertical else (right, left)
    return _between(vertical.x1, horizontal.x1, horizontal.x2) and _between(
        horizontal.y1, vertical.y1, vertical.y2
    )


def _point_on_wire(point: tuple[float, float], wire: Wire) -> bool:
    """Return whether an electrical pin anchor lies on one wire segment."""
    x, y = point
    vertical = math.isclose(wire.x1, wire.x2, abs_tol=_EPS)
    if vertical:
        return math.isclose(x, wire.x1, abs_tol=_EPS) and _between(y, wire.y1, wire.y2)
    return math.isclose(y, wire.y1, abs_tol=_EPS) and _between(x, wire.x1, wire.x2)


def _candidate_trunk_xs(points: list[tuple[float, float]]) -> list[float]:
    xs = [x for x, _ in points]
    min_x, max_x = min(xs), max(xs)
    midpoint = _snap((min_x + max_x) / 2.0)
    candidates = [midpoint]

    # Search symmetrically around the natural midpoint. Four grid steps gives
    # enough visual clearance to avoid immediately adjacent wires/symbol pins.
    stride = 4 * _GRID
    for step in range(1, 9):
        candidates.extend((midpoint + step * stride, midpoint - step * stride))
    candidates.extend((min_x - stride, max_x + stride))

    unique: list[float] = []
    seen: set[float] = set()
    for value in candidates:
        snapped = _coord(_snap(value))
        if snapped not in seen:
            unique.append(snapped)
            seen.add(snapped)
    return unique


def _candidate_trunk_ys(points: list[tuple[float, float]]) -> list[float]:
    ys = [y for _, y in points]
    min_y, max_y = min(ys), max(ys)
    midpoint = _snap((min_y + max_y) / 2.0)
    candidates = [midpoint]
    stride = 4 * _GRID
    for step in range(1, 9):
        candidates.extend((midpoint + step * stride, midpoint - step * stride))
    candidates.extend((min_y - stride, max_y + stride))

    unique: list[float] = []
    seen: set[float] = set()
    for value in candidates:
        snapped = _coord(_snap(value))
        if snapped not in seen:
            unique.append(snapped)
            seen.add(snapped)
    return unique


def _build_trunk_route(
    name: str,
    points: list[tuple[float, float]],
    trunk_x: float,
) -> tuple[list[Wire], NetLabel, list[Junction]]:
    """Build a vertical trunk with horizontal endpoint branches."""
    wires: list[Wire] = []
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for x, y in points:
        _append_wire(wires, seen, (x, y), (trunk_x, y), name)

    ys = sorted({y for _, y in points})
    for y0, y1 in zip(ys, ys[1:]):
        _append_wire(wires, seen, (trunk_x, y0), (trunk_x, y1), name)

    junctions: list[Junction] = []
    if len(points) > 2:
        min_y, max_y = ys[0], ys[-1]
        for y in ys:
            branches = sum(
                1 for x, py in points if py == y and not math.isclose(x, trunk_x, abs_tol=_EPS)
            )
            on_trunk = sum(
                1 for x, py in points if py == y and math.isclose(x, trunk_x, abs_tol=_EPS)
            )
            vertical_sides = int(y > min_y) + int(y < max_y)
            if branches + on_trunk + vertical_sides >= 3:
                junctions.append(Junction(x=trunk_x, y=y, net=name))

    if len(points) == 2 and math.isclose(points[0][1], points[1][1], abs_tol=_EPS):
        label_x = _coord((points[0][0] + points[1][0]) / 2.0)
        label_y = points[0][1]
    elif len(points) == 2 and math.isclose(points[0][0], points[1][0], abs_tol=_EPS):
        label_x = points[0][0]
        label_y = _coord((points[0][1] + points[1][1]) / 2.0)
    else:
        label_x = trunk_x
        label_y = ys[len(ys) // 2]
    return wires, NetLabel(text=name, x=label_x, y=label_y, net=name), junctions


def _build_horizontal_trunk_route(
    name: str,
    points: list[tuple[float, float]],
    trunk_y: float,
) -> tuple[list[Wire], NetLabel, list[Junction]]:
    """Build a horizontal trunk with vertical endpoint branches."""
    wires: list[Wire] = []
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for x, y in points:
        _append_wire(wires, seen, (x, y), (x, trunk_y), name)

    xs = sorted({x for x, _ in points})
    for x0, x1 in zip(xs, xs[1:]):
        _append_wire(wires, seen, (x0, trunk_y), (x1, trunk_y), name)

    junctions: list[Junction] = []
    if len(points) > 2:
        min_x, max_x = xs[0], xs[-1]
        for x in xs:
            branches = sum(
                1 for px, y in points if px == x and not math.isclose(y, trunk_y, abs_tol=_EPS)
            )
            on_trunk = sum(
                1 for px, y in points if px == x and math.isclose(y, trunk_y, abs_tol=_EPS)
            )
            horizontal_sides = int(x > min_x) + int(x < max_x)
            if branches + on_trunk + horizontal_sides >= 3:
                junctions.append(Junction(x=x, y=trunk_y, net=name))

    if len(points) == 2 and math.isclose(points[0][1], points[1][1], abs_tol=_EPS):
        label_x = _coord((points[0][0] + points[1][0]) / 2.0)
        label_y = points[0][1]
    elif len(points) == 2 and math.isclose(points[0][0], points[1][0], abs_tol=_EPS):
        label_x = points[0][0]
        label_y = _coord((points[0][1] + points[1][1]) / 2.0)
    else:
        label_x = xs[len(xs) // 2]
        label_y = trunk_y
    return wires, NetLabel(text=name, x=label_x, y=label_y, net=name), junctions


def _route_collides(
    wires: list[Wire],
    foreign_wires: list[Wire],
    foreign_points: list[tuple[float, float]] | None = None,
) -> bool:
    if any(
        _segments_intersect(candidate, foreign)
        for candidate in wires
        for foreign in foreign_wires
    ):
        return True
    obstacles = foreign_points or []
    return any(_point_on_wire(point, wire) for wire in wires for point in obstacles)


def _route_length(wires: list[Wire]) -> float:
    return sum(abs(wire.x2 - wire.x1) + abs(wire.y2 - wire.y1) for wire in wires)


def _route_bounds(
    wires: list[Wire],
    points: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    for wire in wires:
        xs.extend((wire.x1, wire.x2))
        ys.extend((wire.y1, wire.y2))
    return min(xs), min(ys), max(xs), max(ys)


def _reference_bounds(
    points: list[tuple[float, float]],
    foreign_wires: list[Wire],
) -> tuple[float, float, float, float]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    for wire in foreign_wires:
        xs.extend((wire.x1, wire.x2))
        ys.extend((wire.y1, wire.y2))
    return min(xs), min(ys), max(xs), max(ys)


def _route_score(
    wires: list[Wire],
    points: list[tuple[float, float]],
    foreign_wires: list[Wire],
) -> tuple[float, float, float, int]:
    """Score collision-free geometry for compact, stable incremental routing.

    Expansion outside the already occupied design envelope is deliberately more
    expensive than a small increase in wire length. This prevents the router
    from choosing the first legal escape lane when a similarly short route can
    stay inside the existing drawing. Segment count is a deterministic proxy
    for bends/visual complexity.
    """
    length = _route_length(wires)
    bends = max(0, len(wires) - 1)
    route_min_x, route_min_y, route_max_x, route_max_y = _route_bounds(wires, points)
    ref_min_x, ref_min_y, ref_max_x, ref_max_y = _reference_bounds(points, foreign_wires)
    expansion = (
        max(0.0, ref_min_x - route_min_x)
        + max(0.0, route_max_x - ref_max_x)
        + max(0.0, ref_min_y - route_min_y)
        + max(0.0, route_max_y - ref_max_y)
    )
    total = length + expansion * 4.0 + bends * _GRID
    return total, expansion, length, bends


def _candidate_detours(a: float, b: float) -> list[float]:
    """Return deterministic clearance lanes outside a segment's bounding range."""
    low, high = min(a, b), max(a, b)
    stride = 4 * _GRID
    candidates: list[float] = []
    for step in range(1, 9):
        candidates.extend((low - step * stride, high + step * stride))
    return [_coord(_snap(value)) for value in candidates]


def _build_two_point_dogleg(
    name: str,
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    detour_x: float | None = None,
    detour_y: float | None = None,
) -> tuple[list[Wire], NetLabel, list[Junction]]:
    """Build a three-segment Manhattan dogleg through one clearance lane."""
    if (detour_x is None) == (detour_y is None):
        raise ValueError("exactly one dogleg axis must be provided")

    wires: list[Wire] = []
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    ax, ay = a
    bx, by = b
    if detour_y is not None:
        lane_y = _coord(detour_y)
        _append_wire(wires, seen, a, (ax, lane_y), name)
        _append_wire(wires, seen, (ax, lane_y), (bx, lane_y), name)
        _append_wire(wires, seen, (bx, lane_y), b, name)
        label = NetLabel(
            text=name,
            x=_coord((ax + bx) / 2.0),
            y=lane_y,
            net=name,
        )
    else:
        assert detour_x is not None
        lane_x = _coord(detour_x)
        _append_wire(wires, seen, a, (lane_x, ay), name)
        _append_wire(wires, seen, (lane_x, ay), (lane_x, by), name)
        _append_wire(wires, seen, (lane_x, by), b, name)
        label = NetLabel(
            text=name,
            x=lane_x,
            y=_coord((ay + by) / 2.0),
            net=name,
        )
    return wires, label, []


def _two_point_dogleg_candidates(
    name: str,
    points: list[tuple[float, float]],
    foreign_wires: list[Wire],
    foreign_points: list[tuple[float, float]] | None = None,
) -> list[tuple[list[Wire], NetLabel, list[Junction]]]:
    """Return every collision-free outer dogleg candidate for a two-point net."""
    if len(points) != 2:
        return []
    a, b = points
    result: list[tuple[list[Wire], NetLabel, list[Junction]]] = []
    axes = ("y", "x") if abs(a[0] - b[0]) >= abs(a[1] - b[1]) else ("x", "y")
    for axis in axes:
        values = (
            _candidate_detours(a[1], b[1])
            if axis == "y"
            else _candidate_detours(a[0], b[0])
        )
        for value in values:
            candidate = _build_two_point_dogleg(
                name,
                a,
                b,
                detour_y=value if axis == "y" else None,
                detour_x=value if axis == "x" else None,
            )
            if not _route_collides(candidate[0], foreign_wires, foreign_points):
                result.append(candidate)
    return result


def _route_incremental_geometry(
    name: str,
    endpoints: list[tuple[float, float]],
    foreign_wires: list[Wire],
    foreign_points: list[tuple[float, float]] | None = None,
) -> tuple[list[Wire], NetLabel, list[Junction]]:
    """Route one net without touching foreign wires or foreign pin anchors.

    Vertical and horizontal trunk families are both evaluated for multi-point
    nets. Two-point nets also receive outer Manhattan dogleg candidates. The
    winning geometry is the lowest-cost collision-free route.
    """
    points = sorted(set((_coord(x), _coord(y)) for x, y in endpoints))
    if not points:
        raise ValueError(f"net '{name}' has no drawable endpoints")
    if len(points) == 1:
        x, y = points[0]
        return [], NetLabel(text=name, x=x, y=y, net=name), []

    candidates: list[tuple[list[Wire], NetLabel, list[Junction]]] = []
    for trunk_x in _candidate_trunk_xs(points):
        candidate = _build_trunk_route(name, points, trunk_x)
        if not _route_collides(candidate[0], foreign_wires, foreign_points):
            candidates.append(candidate)

    for trunk_y in _candidate_trunk_ys(points):
        candidate = _build_horizontal_trunk_route(name, points, trunk_y)
        if not _route_collides(candidate[0], foreign_wires, foreign_points):
            candidates.append(candidate)

    candidates.extend(
        _two_point_dogleg_candidates(name, points, foreign_wires, foreign_points)
    )
    if candidates:
        return min(
            candidates,
            key=lambda candidate: _route_score(candidate[0], points, foreign_wires),
        )

    raise RuntimeError(
        f"cannot route net '{name}' without touching existing foreign-net geometry "
        "or a foreign pin anchor; reposition a component or increase placement clearance"
    )


def _foreign_pin_points_for_net(
    circuit: Circuit,
    schematic: Schematic,
    net_name: str,
) -> list[tuple[float, float]]:
    """Return drawable pin anchors that are not members of the routed net."""
    net = circuit.nets[net_name]
    own = {node.key() for node in net.nodes}
    points: set[tuple[float, float]] = set()
    for reference, component in circuit.components.items():
        for pin in component.pins.values():
            key = f"{reference}.{pin.number}"
            if key in own:
                continue
            anchor = _pin_anchor(schematic, reference, pin.number)
            if anchor is not None:
                points.add((_coord(anchor[0]), _coord(anchor[1])))
    return sorted(points)


def route_net_incremental(circuit: Circuit, schematic: Schematic, net_name: str) -> dict:
    """Reroute one Circuit IR net while preserving every unrelated net geometry."""
    net = circuit.nets.get(net_name)
    if net is None:
        raise KeyError(f"net '{net_name}' does not exist")
    if len(net.nodes) < 2:
        raise ValueError(f"net '{net_name}' needs at least two connected pins")

    # Geometry produced by the global composer predates per-net ownership. Do
    # not mix both modes silently because a partial reroute could leave stale
    # unowned wires behind.
    if any(not wire.net for wire in schematic.wires):
        raise RuntimeError(
            "incremental routing cannot be mixed with untagged global-composer wires; "
            "start incremental construction from a fresh project or rollback first"
        )

    endpoints: list[tuple[float, float]] = []
    missing: list[str] = []
    for node in net.nodes:
        anchor = _pin_anchor(schematic, node.component, node.pin)
        if anchor is None:
            missing.append(node.key())
        else:
            endpoints.append(anchor)
    if missing:
        raise ValueError(
            f"cannot locate pin geometry for net '{net_name}': {', '.join(sorted(missing))}"
        )

    foreign_wires = [wire for wire in schematic.wires if wire.net and wire.net != net_name]
    foreign_points = _foreign_pin_points_for_net(circuit, schematic, net_name)
    wires, label, junctions = _route_incremental_geometry(
        net_name,
        endpoints,
        foreign_wires,
        foreign_points,
    )

    schematic.wires = [wire for wire in schematic.wires if wire.net != net_name]
    schematic.labels = [item for item in schematic.labels if item.net != net_name]
    schematic.junctions = [item for item in schematic.junctions if item.net != net_name]

    schematic.wires.extend(wires)
    if not _net_has_named_power_symbol(circuit, net_name):
        schematic.labels.append(label)
    schematic.junctions.extend(junctions)

    route_score, route_expansion, route_length, route_bends = _route_score(
        wires,
        sorted(set((_coord(x), _coord(y)) for x, y in endpoints)),
        foreign_wires,
    )
    return {
        "net": net_name,
        "pins": [node.key() for node in net.nodes],
        "wires": len(wires),
        "labels": 0 if _net_has_named_power_symbol(circuit, net_name) else 1,
        "junctions": len(junctions),
        "route_length_mm": round(route_length, 3),
        "route_expansion_mm": round(route_expansion, 3),
        "route_bends": route_bends,
        "route_score": round(route_score, 3),
    }


def _owned_geometry_nets(schematic: Schematic) -> set[str]:
    nets = {wire.net for wire in schematic.wires if wire.net}
    nets.update(label.net for label in schematic.labels if label.net)
    nets.update(junction.net for junction in schematic.junctions if junction.net)
    return nets


def _foreign_net_intersections(schematic: Schematic) -> list[tuple[str, str]]:
    intersections: set[tuple[str, str]] = set()
    owned = [wire for wire in schematic.wires if wire.net]
    for index, left in enumerate(owned):
        for right in owned[index + 1 :]:
            if left.net == right.net:
                continue
            if _segments_intersect(left, right):
                pair = (min(left.net, right.net), max(left.net, right.net))
                intersections.add(pair)
    return sorted(intersections)


def _foreign_pin_contacts(
    circuit: Circuit,
    schematic: Schematic,
) -> list[tuple[str, str]]:
    """Find wires that touch a pin which is not a member of that wire's net."""
    contacts: set[tuple[str, str]] = set()
    owned_wires = [wire for wire in schematic.wires if wire.net]
    for wire in owned_wires:
        assert wire.net is not None
        net = circuit.nets.get(wire.net)
        if net is None:
            continue
        own = {node.key() for node in net.nodes}
        for reference, component in circuit.components.items():
            for pin in component.pins.values():
                key = f"{reference}.{pin.number}"
                if key in own:
                    continue
                anchor = _pin_anchor(schematic, reference, pin.number)
                if anchor is not None and _point_on_wire(anchor, wire):
                    contacts.add((wire.net, key))
    return sorted(contacts)


def _incremental_semantic_violations(circuit: Circuit, schematic: Schematic) -> list[dict]:
    violations = [
        {"severity": "error", "type": "INVALID_REFERENCE", "description": message}
        for message in circuit.validate_references()
    ]
    routed = _owned_geometry_nets(schematic)
    for name, net in circuit.nets.items():
        if len(net.nodes) >= 2 and name not in routed:
            violations.append(
                {
                    "severity": "error",
                    "type": "NET_NOT_INCREMENTALLY_ROUTED",
                    "description": f"net '{name}' has semantic connections but no incremental geometry",
                }
            )
    for left, right in _foreign_net_intersections(schematic):
        violations.append(
            {
                "severity": "error",
                "type": "FOREIGN_NET_GEOMETRY_INTERSECTION",
                "description": f"incremental geometry for nets '{left}' and '{right}' touches or overlaps",
            }
        )
    for net_name, pin_key in _foreign_pin_contacts(circuit, schematic):
        violations.append(
            {
                "severity": "error",
                "type": "FOREIGN_PIN_GEOMETRY_CONTACT",
                "description": (
                    f"incremental geometry for net '{net_name}' touches foreign pin '{pin_key}'"
                ),
            }
        )
    return violations


def _is_expected_incomplete_erc(item: dict) -> bool:
    """Return true only for errors expected while a circuit is still being assembled."""
    text = str(item.get("description") or item.get("message") or "").lower()
    return (
        "not connected" in text
        or "unconnected" in text
        or "not driven" in text
        or "no driver" in text
    )


def _progressive_erc_view(kicad: dict) -> dict:
    """Keep ERC findings visible but do not block on expected incomplete-circuit errors."""
    result = dict(kicad)
    violations: list[dict] = []
    # A tool/process error can be blocking even without a parsed violation and
    # must never be downgraded by progressive mode.
    blocking = bool(result.get("blocking")) and not bool(result.get("violations"))
    for raw in result.get("violations", []):
        item = dict(raw)
        severity = str(item.get("severity") or "warning").lower()
        ignored = severity in _BLOCKING_SEVERITIES and _is_expected_incomplete_erc(item)
        if ignored:
            item["progressive_ignored"] = True
        elif severity in _BLOCKING_SEVERITIES:
            blocking = True
        violations.append(item)
    result["violations"] = violations
    result["blocking"] = blocking
    result["progressive"] = True
    return result


def validate_incremental_schematic(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    run_external: bool = True,
    allow_incomplete: bool = False,
) -> dict:
    """Validate current incremental geometry without invoking global composition."""
    semantic = _incremental_semantic_violations(circuit, schematic)
    semantic_blocking = bool(semantic)
    if run_external and not semantic_blocking:
        kicad = run_kicad_erc(schematic, resolver)
        if allow_incomplete:
            kicad = _progressive_erc_view(kicad)
    else:
        kicad = {
            "available": False,
            "blocking": False,
            "violations": [],
            "error": "skipped because incremental semantic checks are blocking"
            if semantic_blocking
            else "disabled",
        }
    return {
        "mode": "incremental",
        "allow_incomplete": allow_incomplete,
        "semantic_violations": semantic,
        "kicad": kicad,
        "blocking": semantic_blocking or bool(kicad.get("blocking")),
    }


def export_incremental_schematic(
    circuit: Circuit,
    schematic: Schematic,
    path: str,
    resolver: SymbolResolver | None = None,
    allow_invalid: bool = False,
    run_external: bool = True,
) -> dict:
    """Validate and export the current incremental geometry as KiCad schematic."""
    # Final export is intentionally strict: progressive incomplete-pin handling
    # belongs to checkpoints, never to a production export gate.
    validation = validate_incremental_schematic(
        circuit,
        schematic,
        resolver=resolver,
        run_external=run_external,
        allow_incomplete=False,
    )
    if validation["blocking"] and not allow_invalid:
        return {
            "ok": False,
            "blocked": True,
            "reason": "incremental schematic export blocked by semantic/ERC validation",
            "validation": validation,
        }

    output = validate_output_path(path, {".kicad_sch"})
    text = schematic_to_kicad_sch(schematic, resolver)
    Path(output).write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "exported": output,
        "bytes": len(text.encode("utf-8")),
        "validated": not bool(validation["blocking"]),
        "allow_invalid": allow_invalid,
        "validation": validation,
    }

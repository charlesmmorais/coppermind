"""Incremental schematic routing with KiCad-safe crossing semantics.

The implementation helpers live in :mod:`incremental_core`. This facade keeps
the existing public API and applies a schematic-specific crossing rule: foreign
nets may cross orthogonally when the crossing lies strictly inside both wire
segments and there is no electrical point at the crossing. Collinear overlap,
T/end-point contact, pin contact and junction contact remain blocking.
"""

from __future__ import annotations

import math
from pathlib import Path

from coppermind.circuit import Circuit
from coppermind.libraries import SymbolResolver
from coppermind.schematic import incremental_core as _core
from coppermind.schematic.models import Junction, NetLabel, Schematic, Wire
from coppermind.schematic.composer import symbol_pin_geometry, symbol_sheet_offset
from coppermind.schematic.symbol_geometry import Box, symbol_graphic_box, wire_hits_body
from coppermind.serialize.kicad_sch import _field_boxes, label_clearance_violations

_EPS = _core._EPS
_GRID = _core._GRID
_BLOCKING_SEVERITIES = _core._BLOCKING_SEVERITIES

place_relative_geometry = _core.place_relative_geometry
_segments_intersect = _core._segments_intersect
_point_on_wire = _core._point_on_wire
_route_score = _core._route_score
_route_length = _core._route_length
_wire_key = _core._wire_key
_append_wire = _core._append_wire
_between = _core._between
_candidate_trunk_xs = _core._candidate_trunk_xs
_candidate_trunk_ys = _core._candidate_trunk_ys
_build_trunk_route = _core._build_trunk_route
_build_horizontal_trunk_route = _core._build_horizontal_trunk_route
_route_bounds = _core._route_bounds
_reference_bounds = _core._reference_bounds
_candidate_detours = _core._candidate_detours
_build_two_point_dogleg = _core._build_two_point_dogleg
_two_point_dogleg_candidates = _core._two_point_dogleg_candidates
_owned_geometry_nets = _core._owned_geometry_nets
_foreign_pin_contacts = _core._foreign_pin_contacts
_is_expected_incomplete_erc = _core._is_expected_incomplete_erc
_progressive_erc_view = _core._progressive_erc_view


def _same_point(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return math.isclose(left[0], right[0], abs_tol=_EPS) and math.isclose(
        left[1], right[1], abs_tol=_EPS
    )


def _is_wire_endpoint(point: tuple[float, float], wire: Wire) -> bool:
    endpoints = ((wire.x1, wire.y1), (wire.x2, wire.y2))
    return any(_same_point(point, endpoint) for endpoint in endpoints)


def _perpendicular_crossing_point(left: Wire, right: Wire) -> tuple[float, float] | None:
    """Return a perpendicular crossing point when the two segments meet."""
    left_vertical = math.isclose(left.x1, left.x2, abs_tol=_EPS)
    right_vertical = math.isclose(right.x1, right.x2, abs_tol=_EPS)
    if left_vertical == right_vertical:
        return None
    vertical, horizontal = (left, right) if left_vertical else (right, left)
    point = (_core._coord(vertical.x1), _core._coord(horizontal.y1))
    if not _core._between(point[0], horizontal.x1, horizontal.x2):
        return None
    if not _core._between(point[1], vertical.y1, vertical.y2):
        return None
    return point


def _foreign_wire_contact_is_blocking(left: Wire, right: Wire) -> bool:
    """Allow only a pure interior/interior orthogonal schematic crossing."""
    if not _segments_intersect(left, right):
        return False
    crossing = _perpendicular_crossing_point(left, right)
    if crossing is None:
        return True
    return _is_wire_endpoint(crossing, left) or _is_wire_endpoint(crossing, right)


def _route_collides(
    wires: list[Wire],
    foreign_wires: list[Wire],
    foreign_points: list[tuple[float, float]] | None = None,
    body_boxes: list[Box] | None = None,
) -> bool:
    if any(wire_hits_body(wire, box) for wire in wires for box in body_boxes or []):
        return True
    if any(
        _foreign_wire_contact_is_blocking(candidate, foreign)
        for candidate in wires
        for foreign in foreign_wires
    ):
        return True
    obstacles = foreign_points or []
    return any(_point_on_wire(point, wire) for wire in wires for point in obstacles)


def _route_incremental_geometry(
    name: str,
    endpoints: list[tuple[float, float]],
    foreign_wires: list[Wire],
    foreign_points: list[tuple[float, float]] | None = None,
    body_boxes: list[Box] | None = None,
    escape_directions: dict[tuple[float, float], tuple[float, float]] | None = None,
    field_boxes: list[Box] | None = None,
) -> tuple[list[Wire], NetLabel, list[Junction]]:
    """Route one net while allowing safe graphical crossings of foreign nets."""
    points = sorted(set((_core._coord(x), _core._coord(y)) for x, y in endpoints))
    if not points:
        raise ValueError(f"net '{name}' has no drawable endpoints")
    if len(points) == 1:
        x, y = points[0]
        return [], NetLabel(text=name, x=x, y=y, net=name), []

    # Keep the old broad search, plus nearby body-clearance lanes. Without
    # these, a 2.54mm detour around a connector becomes a 10.16mm excursion
    # and can incorrectly outweigh the component's electrical-flow axis.
    def lanes(seed_points, axis):
        values = _candidate_trunk_xs(seed_points) if axis == 0 else _candidate_trunk_ys(seed_points)
        for box in (body_boxes or []) + (field_boxes or []):
            values.extend(
                (
                    _core._coord(math.floor((box[axis] - 0.635) / _GRID) * _GRID),
                    _core._coord(math.ceil((box[axis + 2] + 0.635) / _GRID) * _GRID),
                )
            )
        return list(dict.fromkeys(values))

    def field_contacts(wires):
        return sum(
            wire_hits_body(wire, box, clearance=0) for wire in wires for box in field_boxes or []
        )

    candidates: list[tuple[list[Wire], NetLabel, list[Junction]]] = []
    for trunk_x in lanes(points, 0):
        candidate = _core._build_trunk_route(name, points, trunk_x)
        if not _route_collides(candidate[0], foreign_wires, foreign_points, body_boxes):
            candidates.append(candidate)
    for trunk_y in lanes(points, 1):
        candidate = _core._build_horizontal_trunk_route(name, points, trunk_y)
        if not _route_collides(candidate[0], foreign_wires, foreign_points, body_boxes):
            candidates.append(candidate)
    for candidate in _core._two_point_dogleg_candidates(name, points, foreign_wires, []):
        if not _route_collides(candidate[0], foreign_wires, foreign_points, body_boxes):
            candidates.append(candidate)

    # Some nets have facing pins at different heights: no single trunk can
    # reach them without passing through a body. Extend each anchor *outward*
    # along its real pin axis, then evaluate the existing trunk families.
    # Bounded local escape lengths; accepted symbols and foreign wires never move.
    if escape_directions and not any(field_contacts(c[0]) == 0 for c in candidates):
        for distance in (_GRID, 2 * _GRID, 4 * _GRID):
            escaped = []
            stubs: list[Wire] = []
            seen: set = set()
            for point in points:
                dx, dy = escape_directions.get(point, (0.0, 0.0))
                end = (
                    _core._coord(point[0] + distance * dx),
                    _core._coord(point[1] + distance * dy),
                )
                escaped.append(end)
                _append_wire(stubs, seen, point, end, name)
            for build, candidate_lanes in (
                (_build_trunk_route, lanes(escaped, 0)),
                (_build_horizontal_trunk_route, lanes(escaped, 1)),
            ):
                for lane in candidate_lanes:
                    wires, label, junctions = build(name, escaped, lane)
                    combined = stubs + wires
                    if not _route_collides(combined, foreign_wires, foreign_points, body_boxes):
                        candidates.append((combined, label, junctions))

    if candidates:
        return min(
            candidates,
            key=lambda candidate: (
                _route_score(candidate[0], points, foreign_wires)[0]
                + 100.0 * field_contacts(candidate[0]),
                _route_score(candidate[0], points, foreign_wires),
            ),
        )
    raise RuntimeError(
        f"cannot route net '{name}' without an unsafe foreign-net contact or protected "
        "electrical point or symbol body; reposition a component or increase placement clearance"
    )


def _foreign_pin_points_for_net(
    circuit: Circuit,
    schematic: Schematic,
    net_name: str,
) -> list[tuple[float, float]]:
    """Treat foreign pins and foreign junctions as protected electrical points."""
    points = set(_core._foreign_pin_points_for_net(circuit, schematic, net_name))
    for junction in schematic.junctions:
        if junction.net and junction.net != net_name:
            points.add((_core._coord(junction.x), _core._coord(junction.y)))
    return sorted(points)


def route_net_incremental(circuit: Circuit, schematic: Schematic, net_name: str) -> dict:
    """Reroute one Circuit IR net while preserving unrelated net geometry."""
    net = circuit.nets.get(net_name)
    if net is None:
        raise KeyError(f"net '{net_name}' does not exist")
    if len(net.nodes) < 2:
        raise ValueError(f"net '{net_name}' needs at least two connected pins")
    if any(not wire.net for wire in schematic.wires):
        raise RuntimeError(
            "incremental routing cannot be mixed with untagged global-composer wires; "
            "start incremental construction from a fresh project or rollback first"
        )

    endpoints: list[tuple[float, float]] = []
    missing: list[str] = []
    for node in net.nodes:
        anchor = _core._pin_anchor(schematic, node.component, node.pin)
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
    body_boxes = list(_body_boxes(schematic).values())
    field_boxes = _field_boxes(schematic, schematic.library_symbols)
    escape_directions = {}
    for node in net.nodes:
        symbol = _core._symbol_by_ref(schematic, node.component)
        library = schematic.library_symbols[symbol.lib_id]
        pin = symbol_pin_geometry(library, symbol.unit)[node.pin]
        angle = math.radians(pin.rotation)
        anchor = _core._pin_anchor(schematic, node.component, node.pin)
        assert anchor is not None  # all missing anchors were rejected above
        escape_directions[anchor] = symbol_sheet_offset(
            -math.cos(angle), -math.sin(angle), symbol.rotation
        )
    wires, label, junctions = _route_incremental_geometry(
        net_name,
        endpoints,
        foreign_wires,
        foreign_points,
        body_boxes,
        escape_directions,
        field_boxes,
    )

    schematic.wires = [wire for wire in schematic.wires if wire.net != net_name]
    schematic.labels = [item for item in schematic.labels if item.net != net_name]
    schematic.junctions = [item for item in schematic.junctions if item.net != net_name]
    schematic.wires.extend(wires)
    if not _core._net_has_named_power_symbol(circuit, net_name):
        schematic.labels.append(label)
    schematic.junctions.extend(junctions)

    route_score, route_expansion, route_length, route_bends = _route_score(
        wires,
        sorted(set((_core._coord(x), _core._coord(y)) for x, y in endpoints)),
        foreign_wires,
    )
    route_score += 100.0 * sum(
        wire_hits_body(wire, box, clearance=0) for wire in wires for box in field_boxes
    )
    return {
        "net": net_name,
        "pins": [node.key() for node in net.nodes],
        "wires": len(wires),
        "labels": 0 if _core._net_has_named_power_symbol(circuit, net_name) else 1,
        "junctions": len(junctions),
        "route_length_mm": round(route_length, 3),
        "route_expansion_mm": round(route_expansion, 3),
        "route_bends": route_bends,
        "route_score": round(route_score, 3),
    }


def _foreign_net_intersections(schematic: Schematic) -> list[tuple[str, str]]:
    """Return only unsafe contacts between geometry owned by different nets."""
    intersections: set[tuple[str, str]] = set()
    owned = [wire for wire in schematic.wires if wire.net]
    junction_points = {
        (_core._coord(junction.x), _core._coord(junction.y))
        for junction in schematic.junctions
        if junction.net
    }
    for index, left in enumerate(owned):
        for right in owned[index + 1 :]:
            if left.net == right.net or not _segments_intersect(left, right):
                continue
            blocking = _foreign_wire_contact_is_blocking(left, right)
            if not blocking:
                crossing = _perpendicular_crossing_point(left, right)
                blocking = crossing is not None and crossing in junction_points
            if blocking:
                intersections.add((min(left.net, right.net), max(left.net, right.net)))
    return sorted(intersections)


def _body_boxes(schematic: Schematic) -> dict[str, Box]:
    result = {}
    for symbol in schematic.symbols:
        # Zero-length power pins coincide with their net glyph; that glyph is
        # intentionally part of the electrical connection, not a device body.
        if symbol.lib_id.lower().startswith("power:"):
            continue
        library = schematic.library_symbols.get(symbol.lib_id)
        box = symbol_graphic_box(symbol, library) if library else None
        if box is not None:
            result[symbol.reference] = box
    return result


def _body_contacts(schematic: Schematic) -> list[tuple[str, str]]:
    return sorted(
        {
            (wire.net, reference)
            for reference, box in _body_boxes(schematic).items()
            for wire in schematic.wires
            if wire_hits_body(wire, box)
        }
    )


def _incremental_semantic_violations(circuit: Circuit, schematic: Schematic) -> list[dict]:
    violations = [
        {"severity": "error", "type": "INVALID_REFERENCE", "description": message}
        for message in circuit.validate_references()
    ]
    routed = _core._owned_geometry_nets(schematic)
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
                "description": (
                    f"incremental geometry for nets '{left}' and '{right}' has an unsafe "
                    "endpoint/junction contact or collinear overlap"
                ),
            }
        )
    for net_name, pin_key in _core._foreign_pin_contacts(circuit, schematic):
        violations.append(
            {
                "severity": "error",
                "type": "FOREIGN_PIN_GEOMETRY_CONTACT",
                "description": (
                    f"incremental geometry for net '{net_name}' touches foreign pin '{pin_key}'"
                ),
            }
        )
    for net_name, reference in _body_contacts(schematic):
        violations.append(
            {
                "severity": "error",
                "type": "WIRE_SYMBOL_BODY_CONTACT",
                "description": f"net '{net_name}' crosses body '{reference}'",
            }
        )
    return violations


def validate_incremental_schematic(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    run_external: bool = True,
    allow_incomplete: bool = False,
) -> dict:
    """Validate current incremental geometry without invoking global composition."""
    semantic = _incremental_semantic_violations(circuit, schematic)
    visual = label_clearance_violations(schematic)
    semantic_blocking = bool(semantic or visual)
    if run_external and not semantic_blocking:
        kicad = _core.run_kicad_erc(schematic, resolver)
        if allow_incomplete:
            kicad = _core._progressive_erc_view(kicad)
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
        "visual_violations": visual,
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
    output = _core.validate_output_path(path, {".kicad_sch"})
    text = _core.schematic_to_kicad_sch(schematic, resolver)
    Path(output).write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "exported": output,
        "bytes": len(text.encode("utf-8")),
        "validated": not bool(validation["blocking"]),
        "allow_invalid": allow_invalid,
        "validation": validation,
    }

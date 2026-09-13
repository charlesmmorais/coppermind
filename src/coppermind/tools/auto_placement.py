"""Cost-based local placement for the incremental schematic authoring loop.

The global composer is intentionally not involved. A candidate move is tried on
an isolated schematic snapshot, every complete semantic net attached to the
moved component is routed on that snapshot, and the best legal relative
position is committed atomically.
"""

from __future__ import annotations

import math
from typing import Any

from coppermind.schematic.incremental import place_relative_geometry, route_net_incremental
from coppermind.schematic.models import Schematic
from coppermind.session import Session

_DIRECTION_ORDER = ("right", "below", "above", "left")
_MIN_CENTER_CLEARANCE = 12.7
_SOFT_CENTER_CLEARANCE = 25.4
_GRID_MM = 2.54
_PAGE_MARGIN_MM = 12.7
_SOFT_EDGE_CLEARANCE_MM = 25.4
_CONNECTED_ANCHOR_PENALTY = 5.0
_EPS = 1e-6

# KiCad drawing-sheet dimensions in landscape orientation, in millimetres.
# Unknown/custom paper names remain unconstrained rather than being guessed.
_PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A5": (210.0, 148.0),
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "LETTER": (279.4, 215.9),
    "LEGAL": (355.6, 215.9),
}


def _impacted_nets(session: Session, reference: str) -> list[str]:
    """Return complete semantic nets that must follow a moved component.

    A net does not need to have geometry yet. This is important for the normal
    agent loop: declare connectivity first with ``connect_pins``, then let auto
    placement choose a position while materializing the affected routes.
    """
    circuit = session.require_circuit()
    return sorted(
        name
        for name, net in circuit.nets.items()
        if len(net.nodes) >= 2 and any(node.component == reference for node in net.nodes)
    )


def _candidate_anchors(
    session: Session,
    reference: str,
    preferred_anchor: str,
    impacted_nets: list[str],
) -> list[str]:
    """Use the requested anchor first, then semantic neighbours as fallbacks."""
    circuit = session.require_circuit()
    result = [preferred_anchor]
    for net_name in impacted_nets:
        net = circuit.nets[net_name]
        for node in net.nodes:
            candidate = node.component
            if candidate == reference or candidate in result:
                continue
            if candidate in circuit.components:
                result.append(candidate)
    return result


def _clear_impacted_geometry(schematic: Schematic, impacted_nets: set[str]) -> None:
    """Drop only stale geometry for nets that will be rerouted in this trial."""
    if not impacted_nets:
        return
    schematic.wires = [wire for wire in schematic.wires if wire.net not in impacted_nets]
    schematic.labels = [label for label in schematic.labels if label.net not in impacted_nets]
    schematic.junctions = [
        junction for junction in schematic.junctions if junction.net not in impacted_nets
    ]


def _stable_bounds(
    schematic: Schematic,
    reference: str,
    impacted_nets: set[str],
) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    for symbol in schematic.symbols:
        if symbol.reference != reference:
            points.append((symbol.x, symbol.y))
    for wire in schematic.wires:
        if not wire.net or wire.net not in impacted_nets:
            points.extend(((wire.x1, wire.y1), (wire.x2, wire.y2)))
    for label in schematic.labels:
        if not label.net or label.net not in impacted_nets:
            points.append((label.x, label.y))
    for junction in schematic.junctions:
        if not junction.net or junction.net not in impacted_nets:
            points.append((junction.x, junction.y))
    if not points:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _candidate_bounds(schematic: Schematic) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    points.extend((symbol.x, symbol.y) for symbol in schematic.symbols)
    for wire in schematic.wires:
        points.extend(((wire.x1, wire.y1), (wire.x2, wire.y2)))
    points.extend((label.x, label.y) for label in schematic.labels)
    points.extend((junction.x, junction.y) for junction in schematic.junctions)
    if not points:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _envelope_expansion(
    stable: tuple[float, float, float, float] | None,
    candidate: tuple[float, float, float, float] | None,
) -> float:
    if stable is None or candidate is None:
        return 0.0
    sx0, sy0, sx1, sy1 = stable
    cx0, cy0, cx1, cy1 = candidate
    return (
        max(0.0, sx0 - cx0)
        + max(0.0, cx1 - sx1)
        + max(0.0, sy0 - cy0)
        + max(0.0, cy1 - sy1)
    )


def _proximity_penalty(schematic: Schematic, reference: str) -> tuple[float, float | None]:
    target = next(symbol for symbol in schematic.symbols if symbol.reference == reference)
    distances: list[float] = []
    for symbol in schematic.symbols:
        if symbol.reference == reference:
            continue
        dx = abs(symbol.x - target.x)
        dy = abs(symbol.y - target.y)
        if dx < _MIN_CENTER_CLEARANCE - _EPS and dy < _MIN_CENTER_CLEARANCE - _EPS:
            raise ValueError(
                f"candidate position for '{reference}' is too close to '{symbol.reference}'"
            )
        distances.append(math.hypot(dx, dy))
    if not distances:
        return 0.0, None
    nearest = min(distances)
    penalty = max(0.0, _SOFT_CENTER_CLEARANCE - nearest) * 2.0
    return penalty, nearest


def _normalize_directions(directions: list[str] | None) -> list[str]:
    if directions is None:
        return list(_DIRECTION_ORDER)
    result: list[str] = []
    for direction in directions:
        if direction not in _DIRECTION_ORDER:
            raise ValueError(
                f"direction must be one of {list(_DIRECTION_ORDER)}; got '{direction}'"
            )
        if direction not in result:
            result.append(direction)
    if not result:
        raise ValueError("directions must contain at least one candidate")
    return result


def _snap_gap(value: float) -> float:
    return round(value / _GRID_MM) * _GRID_MM


def _candidate_gaps(preferred_gap_mm: float) -> list[float]:
    """Try the requested spacing plus compact and relaxed local alternatives."""
    if preferred_gap_mm <= 0:
        raise ValueError("gap_mm must be greater than zero")
    minimum = _GRID_MM * 5.0
    compact = max(minimum, preferred_gap_mm - _GRID_MM * 2.0)
    relaxed = preferred_gap_mm + _GRID_MM * 5.0
    raw = (preferred_gap_mm, compact, relaxed)
    result: list[float] = []
    for value in raw:
        snapped = _snap_gap(value)
        if snapped > 0 and all(abs(snapped - item) > _EPS for item in result):
            result.append(snapped)
    return result


def _paper_dimensions(schematic: Schematic) -> tuple[float, float] | None:
    return _PAPER_SIZES_MM.get(schematic.paper.upper())


def _page_clearance(
    schematic: Schematic,
    bounds: tuple[float, float, float, float] | None,
) -> tuple[float, float | None]:
    """Reject geometry outside the usable page and softly prefer interior space."""
    page = _paper_dimensions(schematic)
    if page is None or bounds is None:
        return 0.0, None
    width, height = page
    x0, y0, x1, y1 = bounds
    left = x0 - _PAGE_MARGIN_MM
    top = y0 - _PAGE_MARGIN_MM
    right = width - _PAGE_MARGIN_MM - x1
    bottom = height - _PAGE_MARGIN_MM - y1
    minimum = min(left, top, right, bottom)
    if minimum < -_EPS:
        raise ValueError(
            "candidate geometry leaves usable "
            f"{schematic.paper} sheet area (margin={_PAGE_MARGIN_MM}mm, "
            f"bounds=({x0:.2f},{y0:.2f})-({x1:.2f},{y1:.2f}))"
        )
    penalty = max(0.0, _SOFT_EDGE_CLEARANCE_MM - minimum) * 1.5
    return penalty, minimum


def component_place_auto(
    session: Session,
    reference: str,
    anchor: str,
    gap_mm: float = 25.4,
    directions: list[str] | None = None,
    lock: bool = True,
    force: bool = False,
) -> dict:
    """Choose the best in-bounds local placement and route its semantic nets."""
    circuit = session.require_circuit()
    if reference not in circuit.components:
        raise KeyError(f"component '{reference}' does not exist")
    if anchor not in circuit.components:
        raise KeyError(f"anchor component '{anchor}' does not exist")
    if reference == anchor:
        raise ValueError("reference and anchor must be different components")

    component = circuit.components[reference]
    if component.properties.get("placement_locked") == "true" and not force:
        raise ValueError(
            f"component '{reference}' placement is locked; pass force=true to reposition it"
        )

    directions_to_try = _normalize_directions(directions)
    gaps_to_try = _candidate_gaps(gap_mm)
    base = session.require_schematic().model_copy(deep=True)
    impacted = _impacted_nets(session, reference)
    impacted_set = set(impacted)
    anchors_to_try = _candidate_anchors(session, reference, anchor, impacted)
    stable_bounds = _stable_bounds(base, reference, impacted_set)

    evaluated: list[dict[str, Any]] = []
    successful: list[tuple[tuple[float, int, int, int], Schematic, dict[str, Any]]] = []

    for anchor_rank, candidate_anchor in enumerate(anchors_to_try):
        anchor_penalty = float(anchor_rank) * _CONNECTED_ANCHOR_PENALTY
        for gap_rank, candidate_gap in enumerate(gaps_to_try):
            for direction_rank, direction in enumerate(directions_to_try):
                trial = base.model_copy(deep=True)
                try:
                    placement = place_relative_geometry(
                        trial,
                        reference,
                        candidate_anchor,
                        direction=direction,
                        gap_mm=candidate_gap,
                    )
                    proximity_penalty, nearest = _proximity_penalty(trial, reference)

                    # Do not let stale geometry from another impacted net constrain this
                    # candidate. Unrelated accepted nets stay untouched and remain hard
                    # obstacles. Impacted nets are then rebuilt deterministically.
                    _clear_impacted_geometry(trial, impacted_set)
                    routes = [
                        route_net_incremental(circuit, trial, net_name)
                        for net_name in impacted
                    ]

                    bounds = _candidate_bounds(trial)
                    edge_penalty, edge_clearance = _page_clearance(trial, bounds)
                    route_score = sum(float(item.get("route_score", 0.0)) for item in routes)
                    route_length = sum(float(item.get("route_length_mm", 0.0)) for item in routes)
                    route_bends = sum(int(item.get("route_bends", 0)) for item in routes)
                    expansion = _envelope_expansion(stable_bounds, bounds)
                    total = (
                        route_score
                        + expansion * 3.0
                        + proximity_penalty
                        + edge_penalty
                        + anchor_penalty
                    )
                    summary: dict[str, Any] = {
                        "anchor": candidate_anchor,
                        "direction": direction,
                        "gap_mm": round(candidate_gap, 3),
                        "ok": True,
                        "score": round(total, 3),
                        "route_score": round(route_score, 3),
                        "route_length_mm": round(route_length, 3),
                        "route_bends": route_bends,
                        "envelope_expansion_mm": round(expansion, 3),
                        "proximity_penalty": round(proximity_penalty, 3),
                        "edge_penalty": round(edge_penalty, 3),
                        "anchor_penalty": round(anchor_penalty, 3),
                        "edge_clearance_mm": (
                            round(edge_clearance, 3) if edge_clearance is not None else None
                        ),
                        "nearest_component_mm": (
                            round(nearest, 3) if nearest is not None else None
                        ),
                        "to": placement["to"],
                        "rerouted_nets": impacted,
                    }
                    evaluated.append(summary)
                    successful.append(
                        (
                            (total, anchor_rank, gap_rank, direction_rank),
                            trial,
                            summary,
                        )
                    )
                except Exception as exc:
                    evaluated.append(
                        {
                            "anchor": candidate_anchor,
                            "direction": direction,
                            "gap_mm": round(candidate_gap, 3),
                            "ok": False,
                            "error": str(exc),
                        }
                    )

    if not successful:
        errors = "; ".join(
            f"{item['anchor']}:{item['direction']}@{item['gap_mm']}mm: "
            f"{item.get('error', 'rejected')}"
            for item in evaluated
        )
        raise RuntimeError(f"no legal automatic placement for '{reference}': {errors}")

    _, best_schematic, best = min(successful, key=lambda item: item[0])
    session.schematic = best_schematic
    if lock:
        component.properties["placement_locked"] = "true"
    elif force:
        component.properties.pop("placement_locked", None)

    return {
        "ok": True,
        "reference": reference,
        "anchor": anchor,
        "chosen_anchor": best["anchor"],
        "gap_mm": gap_mm,
        "chosen_gap_mm": best["gap_mm"],
        "chosen_direction": best["direction"],
        "score": best["score"],
        "to": best["to"],
        "rerouted_nets": impacted,
        "locked": component.properties.get("placement_locked") == "true",
        "candidates": evaluated,
        "pending_commit": True,
    }

"""Cost-based local placement for the incremental schematic authoring loop.

The global composer is intentionally not involved.  A candidate move is tried on
an isolated schematic snapshot, only nets owned by the moved component are
rerouted, and the best legal relative direction is committed atomically.
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
_EPS = 1e-6


def _owned_geometry_nets(schematic: Schematic) -> set[str]:
    nets = {wire.net for wire in schematic.wires if wire.net}
    nets.update(label.net for label in schematic.labels if label.net)
    nets.update(junction.net for junction in schematic.junctions if junction.net)
    return nets


def _impacted_nets(session: Session, reference: str) -> list[str]:
    circuit = session.require_circuit()
    routed = _owned_geometry_nets(session.require_schematic())
    return sorted(
        name
        for name, net in circuit.nets.items()
        if name in routed and any(node.component == reference for node in net.nodes)
    )


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


def component_place_auto(
    session: Session,
    reference: str,
    anchor: str,
    gap_mm: float = 25.4,
    directions: list[str] | None = None,
    lock: bool = True,
    force: bool = False,
) -> dict:
    """Choose the best local relative placement without moving accepted geometry."""
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

    candidates = _normalize_directions(directions)
    base = session.require_schematic().model_copy(deep=True)
    impacted = _impacted_nets(session, reference)
    impacted_set = set(impacted)
    stable_bounds = _stable_bounds(base, reference, impacted_set)

    evaluated: list[dict[str, Any]] = []
    successful: list[tuple[tuple[float, int], Schematic, dict[str, Any]]] = []

    for rank, direction in enumerate(candidates):
        trial = base.model_copy(deep=True)
        try:
            placement = place_relative_geometry(
                trial,
                reference,
                anchor,
                direction=direction,
                gap_mm=gap_mm,
            )
            proximity_penalty, nearest = _proximity_penalty(trial, reference)
            routes = [
                route_net_incremental(circuit, trial, net_name)
                for net_name in impacted
            ]
            route_score = sum(float(item.get("route_score", 0.0)) for item in routes)
            route_length = sum(float(item.get("route_length_mm", 0.0)) for item in routes)
            route_bends = sum(int(item.get("route_bends", 0)) for item in routes)
            expansion = _envelope_expansion(stable_bounds, _candidate_bounds(trial))
            total = route_score + expansion * 3.0 + proximity_penalty
            summary: dict[str, Any] = {
                "direction": direction,
                "ok": True,
                "score": round(total, 3),
                "route_score": round(route_score, 3),
                "route_length_mm": round(route_length, 3),
                "route_bends": route_bends,
                "envelope_expansion_mm": round(expansion, 3),
                "proximity_penalty": round(proximity_penalty, 3),
                "nearest_component_mm": round(nearest, 3) if nearest is not None else None,
                "to": placement["to"],
                "rerouted_nets": impacted,
            }
            evaluated.append(summary)
            successful.append(((total, rank), trial, summary))
        except Exception as exc:
            evaluated.append(
                {
                    "direction": direction,
                    "ok": False,
                    "error": str(exc),
                }
            )

    if not successful:
        errors = "; ".join(
            f"{item['direction']}: {item.get('error', 'rejected')}" for item in evaluated
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
        "gap_mm": gap_mm,
        "chosen_direction": best["direction"],
        "score": best["score"],
        "to": best["to"],
        "rerouted_nets": impacted,
        "locked": component.properties.get("placement_locked") == "true",
        "candidates": evaluated,
        "pending_commit": True,
    }

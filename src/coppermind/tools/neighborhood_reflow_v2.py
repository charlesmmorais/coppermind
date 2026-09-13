"""Target-weighted bounded neighborhood reflow for incremental schematics.

The first neighborhood optimizer proved the safety contract (bounded semantic
scope, frozen outside components and selective rerouting) but could keep a late
component in a visually expensive local minimum.  V2 keeps the same safety
contract and adds a target-centric local slot search plus a cost function that
weights the nets attached to the late component more strongly.
"""

from __future__ import annotations

import math
from typing import Any

from coppermind.schematic.incremental import route_net_incremental
from coppermind.schematic.models import Schematic
from coppermind.session import Session
from coppermind.tools.auto_placement import (
    _candidate_bounds,
    _candidate_gaps,
    _page_clearance,
)
from coppermind.tools.neighborhood_reflow import (
    _clear_net_geometry,
    _component_graph,
    _impacted_nets,
    _movement_metrics,
    _positions,
    _semantic_neighborhood,
    _validate_symbol_clearance,
)
from coppermind.schematic.incremental import place_relative_geometry

_DIRECTION_ORDER = ("right", "below", "above", "left")
_GRID_MM = 2.54
_LOCAL_STEP_MM = 12.7
_LOCAL_PADDING_MM = 50.8
_LOCAL_MAX_CANDIDATES = 96
_FOCUS_ROUTE_WEIGHT = 3.0
_SECONDARY_ROUTE_WEIGHT = 1.0
_MOVEMENT_WEIGHT = 0.20
_MOVED_COMPONENT_PENALTY = 2.0
_COMPACTNESS_WEIGHT = 0.12
_EPS = 1e-6


def _focus_nets(session: Session, reference: str) -> list[str]:
    circuit = session.require_circuit()
    return sorted(
        name
        for name, net in circuit.nets.items()
        if len(net.nodes) >= 2 and any(node.component == reference for node in net.nodes)
    )


def _compactness(schematic: Schematic) -> float:
    bounds = _candidate_bounds(schematic)
    if bounds is None:
        return 0.0
    x0, y0, x1, y1 = bounds
    return max(0.0, x1 - x0) + max(0.0, y1 - y0)


def _score_state(
    session: Session,
    source: Schematic,
    impacted: list[str],
    focus: set[str],
    baseline_positions: dict[str, tuple[float, float]],
) -> tuple[float, Schematic, dict[str, Any]]:
    """Reroute and score a neighborhood state, emphasizing the target nets."""
    circuit = session.require_circuit()
    trial = source.model_copy(deep=True)
    _validate_symbol_clearance(trial)
    _clear_net_geometry(trial, set(impacted))

    routes = [route_net_incremental(circuit, trial, name) for name in impacted]
    bounds = _candidate_bounds(trial)
    edge_penalty, edge_clearance = _page_clearance(trial, bounds)
    movement_mm, moved_count, moved = _movement_metrics(baseline_positions, trial)

    weighted_route_score = 0.0
    route_score = 0.0
    route_length = 0.0
    focus_route_length = 0.0
    focus_route_score = 0.0
    route_bends = 0
    by_net: dict[str, dict[str, float | int]] = {}
    for route in routes:
        name = str(route["net"])
        score = float(route["route_score"])
        length = float(route["route_length_mm"])
        bends = int(route["route_bends"])
        weight = _FOCUS_ROUTE_WEIGHT if name in focus else _SECONDARY_ROUTE_WEIGHT
        weighted_route_score += score * weight
        route_score += score
        route_length += length
        route_bends += bends
        if name in focus:
            focus_route_length += length
            focus_route_score += score
        by_net[name] = {
            "route_score": round(score, 3),
            "route_length_mm": round(length, 3),
            "route_bends": bends,
            "weight": weight,
        }

    compactness = _compactness(trial)
    total = (
        weighted_route_score
        + movement_mm * _MOVEMENT_WEIGHT
        + moved_count * _MOVED_COMPONENT_PENALTY
        + compactness * _COMPACTNESS_WEIGHT
        + edge_penalty
    )
    metrics: dict[str, Any] = {
        "score": round(total, 3),
        "weighted_route_score": round(weighted_route_score, 3),
        "route_score": round(route_score, 3),
        "route_length_mm": round(route_length, 3),
        "focus_route_score": round(focus_route_score, 3),
        "focus_route_length_mm": round(focus_route_length, 3),
        "route_bends": route_bends,
        "movement_mm": round(movement_mm, 3),
        "moved_components": moved,
        "compactness_span_mm": round(compactness, 3),
        "edge_penalty": round(edge_penalty, 3),
        "edge_clearance_mm": round(edge_clearance, 3) if edge_clearance is not None else None,
        "routes": by_net,
        "rerouted_nets": impacted,
    }
    return total, trial, metrics


def _symbol_position(schematic: Schematic, reference: str) -> tuple[float, float]:
    symbol = next((item for item in schematic.symbols if item.reference == reference), None)
    if symbol is None:
        raise KeyError(f"schematic symbol '{reference}' does not exist")
    return symbol.x, symbol.y


def _move_symbol_to(schematic: Schematic, reference: str, x: float, y: float) -> None:
    symbol = next((item for item in schematic.symbols if item.reference == reference), None)
    if symbol is None:
        raise KeyError(f"schematic symbol '{reference}' does not exist")
    symbol.x = round(x / _GRID_MM) * _GRID_MM
    symbol.y = round(y / _GRID_MM) * _GRID_MM


def _local_slot_points(
    session: Session,
    schematic: Schematic,
    reference: str,
    neighborhood: list[str],
) -> list[tuple[float, float]]:
    """Return bounded target slots around its semantic neighborhood.

    The search is intentionally local and deterministic.  It can express a
    useful diagonal slot that four direction-only relative moves cannot.
    """
    current_x, current_y = _symbol_position(schematic, reference)
    other_refs = [item for item in neighborhood if item != reference]
    other_positions = [_symbol_position(schematic, item) for item in other_refs]
    if not other_positions:
        return []

    xs = [x for x, _ in other_positions]
    ys = [y for _, y in other_positions]
    min_x = min(xs) - _LOCAL_PADDING_MM
    max_x = max(xs) + _LOCAL_PADDING_MM
    min_y = min(ys) - _LOCAL_PADDING_MM
    max_y = max(ys) + _LOCAL_PADDING_MM

    points: list[tuple[float, float]] = []
    x = math.floor(min_x / _LOCAL_STEP_MM) * _LOCAL_STEP_MM
    while x <= max_x + _EPS:
        y = math.floor(min_y / _LOCAL_STEP_MM) * _LOCAL_STEP_MM
        while y <= max_y + _EPS:
            sx = round(round(x / _GRID_MM) * _GRID_MM, 6)
            sy = round(round(y / _GRID_MM) * _GRID_MM, 6)
            if abs(sx - current_x) > _EPS or abs(sy - current_y) > _EPS:
                points.append((sx, sy))
            y += _LOCAL_STEP_MM
        x += _LOCAL_STEP_MM

    # Prefer slots that are collectively close to the semantic neighbours, then
    # slots that require less movement from the current target position.
    points = sorted(set(points))
    points.sort(
        key=lambda point: (
            sum(abs(point[0] - x) + abs(point[1] - y) for x, y in other_positions),
            abs(point[0] - current_x) + abs(point[1] - current_y),
            point[1],
            point[0],
        )
    )
    return points[:_LOCAL_MAX_CANDIDATES]


def _anchors_for(session: Session, reference: str, neighborhood: list[str]) -> list[str]:
    graph = _component_graph(session)
    neighbours = [item for item in sorted(graph[reference]) if item in neighborhood]
    fallbacks = [item for item in neighborhood if item != reference and item not in neighbours]
    return neighbours + fallbacks


def component_reflow_neighborhood(
    session: Session,
    reference: str,
    max_components: int = 4,
    passes: int = 2,
    gap_mm: float = 25.4,
    min_improvement: float = 1.0,
) -> dict:
    """Compact a bounded semantic neighborhood with a target-weighted local search."""
    if passes < 1 or passes > 3:
        raise ValueError("passes must be between 1 and 3")
    if not math.isfinite(min_improvement) or min_improvement < 0:
        raise ValueError("min_improvement must be a non-negative finite number")

    neighborhood = _semantic_neighborhood(session, reference, max_components)
    selected = set(neighborhood)
    impacted = _impacted_nets(session, selected)
    focus = set(_focus_nets(session, reference))
    if not impacted:
        raise ValueError("semantic neighborhood has no complete nets to optimize")
    if not focus:
        raise ValueError(f"component '{reference}' has no complete nets to optimize")

    base = session.require_schematic().model_copy(deep=True)
    baseline_positions = _positions(base, neighborhood)
    outside_positions = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in base.symbols
        if symbol.reference not in selected
    }

    baseline_score, best_schematic, baseline_metrics = _score_state(
        session, base, impacted, focus, baseline_positions
    )
    best_score = baseline_score
    history: list[dict[str, Any]] = []
    target_candidates = 0

    # Stage 1: search a bounded local 2-D slot for the late/target component.
    # This breaks the common local minimum where no one-axis relative move is
    # attractive even though a nearby diagonal slot is much better.
    for x, y in _local_slot_points(session, base, reference, neighborhood):
        target_candidates += 1
        candidate = base.model_copy(deep=True)
        try:
            _move_symbol_to(candidate, reference, x, y)
            score, routed, metrics = _score_state(
                session, candidate, impacted, focus, baseline_positions
            )
        except Exception:
            continue
        if score + min_improvement < best_score:
            best_score = score
            best_schematic = routed
            history.append(
                {
                    "stage": "target-slot",
                    "reference": reference,
                    "to": {"x": x, "y": y},
                    **metrics,
                }
            )

    # Stage 2: bounded coordinate descent can tidy direct semantic neighbours
    # around the better target slot.  Outside components remain hard-frozen.
    gaps = _candidate_gaps(gap_mm)
    for pass_index in range(passes):
        improved_this_pass = False
        for moving in neighborhood:
            anchors = _anchors_for(session, moving, neighborhood)
            local_best_score = best_score
            local_best: Schematic | None = None
            local_summary: dict[str, Any] | None = None

            for anchor in anchors:
                for candidate_gap in gaps:
                    for direction in _DIRECTION_ORDER:
                        candidate = best_schematic.model_copy(deep=True)
                        try:
                            placement = place_relative_geometry(
                                candidate,
                                moving,
                                anchor,
                                direction=direction,
                                gap_mm=candidate_gap,
                            )
                            score, routed, metrics = _score_state(
                                session,
                                candidate,
                                impacted,
                                focus,
                                baseline_positions,
                            )
                        except Exception:
                            continue
                        if score + min_improvement < local_best_score:
                            local_best_score = score
                            local_best = routed
                            local_summary = {
                                "stage": "coordinate-descent",
                                "pass": pass_index + 1,
                                "reference": moving,
                                "anchor": anchor,
                                "direction": direction,
                                "gap_mm": round(candidate_gap, 3),
                                "to": placement["to"],
                                **metrics,
                            }

            if local_best is not None and local_summary is not None:
                best_schematic = local_best
                best_score = local_best_score
                history.append(local_summary)
                improved_this_pass = True

        if not improved_this_pass:
            break

    final_outside = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in best_schematic.symbols
        if symbol.reference not in selected
    }
    if final_outside != outside_positions:
        raise RuntimeError("neighborhood reflow attempted to move a component outside its boundary")

    final_movement_mm, _count, moved = _movement_metrics(baseline_positions, best_schematic)
    final_score, final_schematic, final_metrics = _score_state(
        session, best_schematic, impacted, focus, baseline_positions
    )
    improved = final_score + _EPS < baseline_score
    if improved:
        session.schematic = final_schematic

    return {
        "ok": True,
        "reference": reference,
        "neighborhood": neighborhood,
        "focus_nets": sorted(focus),
        "rerouted_nets": impacted,
        "improved": improved,
        "baseline_score": round(baseline_score, 3),
        "score": round(final_score, 3),
        "score_improvement": round(max(0.0, baseline_score - final_score), 3),
        "movement_mm": round(final_movement_mm if improved else 0.0, 3),
        "moved_components": moved if improved else [],
        "baseline": baseline_metrics,
        "final": final_metrics,
        "target_slot_candidates": target_candidates,
        "accepted_moves": history,
        "outside_components_frozen": True,
        "pending_commit": improved,
    }

"""Target-first bounded neighborhood reflow for incremental schematics.

V1 proved the safety contract (bounded semantic scope, frozen outside components
and selective rerouting). V2 added a local 2-D search, but a global neighborhood
score could still reject a clearly better position for the late component. This
revision makes the operation explicitly target-first: first shorten only the
nets attached to the target while every other net remains a hard obstacle, then
optionally tidy semantic neighbours without allowing those focus nets to regress.
"""

from __future__ import annotations

import math
from typing import Any

from coppermind.schematic.incremental import place_relative_geometry, route_net_incremental
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

_DIRECTION_ORDER = ("right", "below", "above", "left")
_GRID_MM = 2.54
_LOCAL_STEP_MM = 5.08
_LOCAL_PADDING_MM = 38.1
_LOCAL_MAX_CANDIDATES = 512
_FOCUS_ROUTE_WEIGHT = 4.0
_SECONDARY_ROUTE_WEIGHT = 1.0
_MOVEMENT_WEIGHT = 0.15
_MOVED_COMPONENT_PENALTY = 2.0
_COMPACTNESS_WEIGHT = 0.08
_TARGET_MOVEMENT_WEIGHT = 0.03
_TARGET_COMPACTNESS_WEIGHT = 0.03
_EPS = 1e-6


def _focus_nets(session: Session, reference: str) -> list[str]:
    circuit = session.require_circuit()
    return sorted(
        name
        for name, net in circuit.nets.items()
        if len(net.nodes) >= 2 and any(node.component == reference for node in net.nodes)
    )


def _focus_neighbor_refs(session: Session, reference: str, focus: set[str]) -> list[str]:
    circuit = session.require_circuit()
    result: list[str] = []
    for name in sorted(focus):
        for node in circuit.nets[name].nodes:
            candidate = node.component
            if candidate == reference or candidate in result:
                continue
            if candidate in circuit.components:
                result.append(candidate)
    return result


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
    """Reroute and score the whole selected neighborhood with focus weighting."""
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


def _score_target_state(
    session: Session,
    source: Schematic,
    reference: str,
    focus: set[str],
    baseline_target: tuple[float, float],
) -> tuple[float, Schematic, dict[str, Any]]:
    """Score only the target's own nets while preserving every other net geometry.

    This is the critical target-first stage. Non-focus nets stay exactly where
    they were and act as routing obstacles, so a useful R9 move is not rejected
    merely because VOUT/GND would be globally rerouted differently.
    """
    circuit = session.require_circuit()
    trial = source.model_copy(deep=True)
    _validate_symbol_clearance(trial)
    ordered_focus = sorted(focus, key=lambda name: (-len(circuit.nets[name].nodes), name))
    _clear_net_geometry(trial, focus)
    routes = [route_net_incremental(circuit, trial, name) for name in ordered_focus]

    bounds = _candidate_bounds(trial)
    edge_penalty, edge_clearance = _page_clearance(trial, bounds)
    target_x, target_y = _symbol_position(trial, reference)
    movement_mm = abs(target_x - baseline_target[0]) + abs(target_y - baseline_target[1])
    route_score = sum(float(route["route_score"]) for route in routes)
    route_length = sum(float(route["route_length_mm"]) for route in routes)
    route_bends = sum(int(route["route_bends"]) for route in routes)
    compactness = _compactness(trial)

    # Length is explicit here rather than relying only on the router's score.
    # For a late bridging component this strongly rewards the human-like choice:
    # place it near the two rails/nodes it actually connects.
    total = (
        route_score * 2.0
        + route_length * 2.5
        + route_bends * 4.0
        + movement_mm * _TARGET_MOVEMENT_WEIGHT
        + compactness * _TARGET_COMPACTNESS_WEIGHT
        + edge_penalty
    )
    by_net = {
        str(route["net"]): {
            "route_score": round(float(route["route_score"]), 3),
            "route_length_mm": round(float(route["route_length_mm"]), 3),
            "route_bends": int(route["route_bends"]),
        }
        for route in routes
    }
    metrics: dict[str, Any] = {
        "score": round(total, 3),
        "focus_route_score": round(route_score, 3),
        "focus_route_length_mm": round(route_length, 3),
        "focus_route_bends": route_bends,
        "target_movement_mm": round(movement_mm, 3),
        "compactness_span_mm": round(compactness, 3),
        "edge_penalty": round(edge_penalty, 3),
        "edge_clearance_mm": round(edge_clearance, 3) if edge_clearance is not None else None,
        "routes": by_net,
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


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _local_slot_points(
    session: Session,
    schematic: Schematic,
    reference: str,
    neighborhood: list[str],
    focus: set[str],
) -> list[tuple[float, float]]:
    """Return dense bounded target slots around focus-net semantic neighbours."""
    current_x, current_y = _symbol_position(schematic, reference)
    focus_refs = _focus_neighbor_refs(session, reference, focus)
    focus_positions = [_symbol_position(schematic, item) for item in focus_refs]
    fallback_refs = [item for item in neighborhood if item != reference and item not in focus_refs]
    fallback_positions = [_symbol_position(schematic, item) for item in fallback_refs]
    anchor_positions = focus_positions or fallback_positions
    if not anchor_positions:
        return []

    xs = [x for x, _ in anchor_positions]
    ys = [y for _, y in anchor_positions]
    min_x = min(xs) - _LOCAL_PADDING_MM
    max_x = max(xs) + _LOCAL_PADDING_MM
    min_y = min(ys) - _LOCAL_PADDING_MM
    max_y = max(ys) + _LOCAL_PADDING_MM

    points: set[tuple[float, float]] = set()

    # Seed a dense 5x5 neighbourhood around the geometric median of the actual
    # components on the target's focus nets. This catches the common bridge slot
    # directly instead of hoping a coarse page scan lands on it.
    center_x = _median(xs)
    center_y = _median(ys)
    offsets = (-25.4, -12.7, 0.0, 12.7, 25.4)
    for dx in offsets:
        for dy in offsets:
            sx = round(round((center_x + dx) / _GRID_MM) * _GRID_MM, 6)
            sy = round(round((center_y + dy) / _GRID_MM) * _GRID_MM, 6)
            points.add((sx, sy))

    x = math.floor(min_x / _LOCAL_STEP_MM) * _LOCAL_STEP_MM
    while x <= max_x + _EPS:
        y = math.floor(min_y / _LOCAL_STEP_MM) * _LOCAL_STEP_MM
        while y <= max_y + _EPS:
            sx = round(round(x / _GRID_MM) * _GRID_MM, 6)
            sy = round(round(y / _GRID_MM) * _GRID_MM, 6)
            points.add((sx, sy))
            y += _LOCAL_STEP_MM
        x += _LOCAL_STEP_MM

    points.discard((round(current_x, 6), round(current_y, 6)))
    ordered = list(points)
    ordered.sort(
        key=lambda point: (
            sum(abs(point[0] - x) + abs(point[1] - y) for x, y in focus_positions)
            if focus_positions
            else sum(abs(point[0] - x) + abs(point[1] - y) for x, y in fallback_positions),
            abs(point[0] - center_x) + abs(point[1] - center_y),
            abs(point[0] - current_x) + abs(point[1] - current_y),
            point[1],
            point[0],
        )
    )
    return ordered[:_LOCAL_MAX_CANDIDATES]


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
    """Compact a bounded semantic neighborhood using a target-first search."""
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
    baseline_target = baseline_positions[reference]
    outside_positions = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in base.symbols
        if symbol.reference not in selected
    }

    baseline_global_score, _baseline_global_schematic, baseline_metrics = _score_state(
        session, base, impacted, focus, baseline_positions
    )
    baseline_target_score, _baseline_target_schematic, baseline_focus = _score_target_state(
        session, base, reference, focus, baseline_target
    )

    history: list[dict[str, Any]] = []
    target_candidates = 0
    target_best_score = baseline_target_score
    target_best_focus_length = float(baseline_focus["focus_route_length_mm"])
    target_best = base.model_copy(deep=True)
    target_best_summary: dict[str, Any] | None = None

    # Stage 1: move only the target and reroute only its own nets. Every other
    # accepted net remains frozen and acts as a hard routing obstacle.
    for x, y in _local_slot_points(session, base, reference, neighborhood, focus):
        target_candidates += 1
        candidate = base.model_copy(deep=True)
        try:
            _move_symbol_to(candidate, reference, x, y)
            score, routed, metrics = _score_target_state(
                session, candidate, reference, focus, baseline_target
            )
        except Exception:
            continue
        focus_length = float(metrics["focus_route_length_mm"])
        if (
            focus_length + max(_GRID_MM, min_improvement) < target_best_focus_length
            and score + min_improvement < target_best_score
        ):
            target_best_score = score
            target_best_focus_length = focus_length
            target_best = routed
            target_best_summary = {
                "stage": "target-first-slot",
                "reference": reference,
                "to": {"x": x, "y": y},
                **metrics,
            }

    if target_best_summary is not None:
        history.append(target_best_summary)

    # Establish a global routed state from the compact target position. This is
    # deliberately after target selection, so secondary VOUT/GND rerouting cannot
    # veto a clearly shorter VIN/SENSE bridge.
    try:
        best_score, best_schematic, best_metrics = _score_state(
            session, target_best, impacted, focus, baseline_positions
        )
    except Exception:
        best_score = baseline_global_score
        best_schematic = target_best
        best_metrics = baseline_metrics

    # Stage 2: tidy only semantic neighbours. The target itself stays in its
    # chosen slot, and a neighbour move is accepted only if the global score
    # improves without making the focus-net length worse.
    best_focus_score, best_schematic, best_focus_metrics = _score_target_state(
        session, best_schematic, reference, focus, baseline_target
    )
    best_focus_length = float(best_focus_metrics["focus_route_length_mm"])
    gaps = _candidate_gaps(gap_mm)

    for pass_index in range(passes):
        improved_this_pass = False
        for moving in [item for item in neighborhood if item != reference]:
            anchors = _anchors_for(session, moving, neighborhood)
            local_best_score = best_score
            local_best_focus_score = best_focus_score
            local_best_focus_length = best_focus_length
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
                            focus_score, focus_routed, focus_metrics = _score_target_state(
                                session,
                                routed,
                                reference,
                                focus,
                                baseline_target,
                            )
                        except Exception:
                            continue
                        focus_length = float(focus_metrics["focus_route_length_mm"])
                        if (
                            score + min_improvement < local_best_score
                            and focus_length <= local_best_focus_length + _EPS
                        ):
                            local_best_score = score
                            local_best_focus_score = focus_score
                            local_best_focus_length = focus_length
                            local_best = focus_routed
                            local_summary = {
                                "stage": "neighbor-tidy",
                                "pass": pass_index + 1,
                                "reference": moving,
                                "anchor": anchor,
                                "direction": direction,
                                "gap_mm": round(candidate_gap, 3),
                                "to": placement["to"],
                                **metrics,
                                "focus_after": focus_metrics,
                            }

            if local_best is not None and local_summary is not None:
                best_schematic = local_best
                best_score = local_best_score
                best_focus_score = local_best_focus_score
                best_focus_length = local_best_focus_length
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

    # One last focus-only route makes the output deterministic while preserving
    # the non-focus geometry chosen by the bounded neighbourhood pass.
    final_focus_score, final_schematic, final_focus_metrics = _score_target_state(
        session, best_schematic, reference, focus, baseline_target
    )
    final_focus_length = float(final_focus_metrics["focus_route_length_mm"])
    focus_gain = float(baseline_focus["focus_route_length_mm"]) - final_focus_length
    final_movement_mm, _count, moved = _movement_metrics(baseline_positions, final_schematic)
    improved = focus_gain > _EPS or best_score + _EPS < baseline_global_score
    if improved:
        session.schematic = final_schematic

    target_to = _symbol_position(final_schematic, reference)
    final_metrics = dict(best_metrics)
    final_metrics["focus_route_length_mm"] = round(final_focus_length, 3)
    final_metrics["focus_route_score"] = round(
        float(final_focus_metrics["focus_route_score"]), 3
    )

    return {
        "ok": True,
        "reference": reference,
        "neighborhood": neighborhood,
        "focus_nets": sorted(focus),
        "rerouted_nets": impacted,
        "improved": improved,
        "baseline_score": round(baseline_global_score, 3),
        "score": round(best_score, 3),
        "score_improvement": round(max(0.0, baseline_global_score - best_score), 3),
        "baseline_focus_route_length_mm": round(
            float(baseline_focus["focus_route_length_mm"]), 3
        ),
        "focus_route_length_mm": round(final_focus_length, 3),
        "focus_route_gain_mm": round(max(0.0, focus_gain), 3),
        "target_from": {"x": baseline_target[0], "y": baseline_target[1]},
        "target_to": {"x": target_to[0], "y": target_to[1]},
        "movement_mm": round(final_movement_mm if improved else 0.0, 3),
        "moved_components": moved if improved else [],
        "baseline": baseline_metrics,
        "baseline_focus": baseline_focus,
        "final": final_metrics,
        "final_focus": final_focus_metrics,
        "target_slot_candidates": target_candidates,
        "accepted_moves": history,
        "outside_components_frozen": True,
        "pending_commit": improved,
        "target_first": True,
        "target_focus_score": round(final_focus_score, 3),
    }

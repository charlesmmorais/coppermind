"""Bounded semantic-neighborhood reflow for incremental schematic authoring.

Incremental placement intentionally freezes accepted geometry.  That is a good
safety default, but late components can become boxed into visually poor legal
positions.  This module provides a second-stage optimizer: reconsider only a
small electrically connected neighborhood, reroute only nets touching that
neighborhood, and keep the rest of the schematic frozen.
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

_DIRECTION_ORDER = ("right", "below", "above", "left")
_MIN_CENTER_CLEARANCE_MM = 12.7
_MOVEMENT_WEIGHT = 0.75
_MOVED_COMPONENT_PENALTY = 7.5
_COMPACTNESS_WEIGHT = 0.20
_EPS = 1e-6


def _component_graph(session: Session) -> dict[str, set[str]]:
    circuit = session.require_circuit()
    graph: dict[str, set[str]] = {reference: set() for reference in circuit.components}
    for net in circuit.nets.values():
        refs = sorted({node.component for node in net.nodes if node.component in graph})
        for index, left in enumerate(refs):
            for right in refs[index + 1 :]:
                graph[left].add(right)
                graph[right].add(left)
    return graph


def _semantic_neighborhood(
    session: Session,
    reference: str,
    max_components: int,
) -> list[str]:
    """Return a deterministic BFS neighborhood, always including ``reference``."""
    circuit = session.require_circuit()
    if reference not in circuit.components:
        raise KeyError(f"component '{reference}' does not exist")
    if max_components < 2 or max_components > 6:
        raise ValueError("max_components must be between 2 and 6")

    graph = _component_graph(session)
    result = [reference]
    queue = [reference]
    seen = {reference}
    while queue and len(result) < max_components:
        current = queue.pop(0)
        for neighbour in sorted(graph[current]):
            if neighbour in seen:
                continue
            seen.add(neighbour)
            result.append(neighbour)
            queue.append(neighbour)
            if len(result) >= max_components:
                break
    return result


def _impacted_nets(session: Session, references: set[str]) -> list[str]:
    circuit = session.require_circuit()
    nets = [
        name
        for name, net in circuit.nets.items()
        if len(net.nodes) >= 2 and any(node.component in references for node in net.nodes)
    ]
    # Reserve the high-fanout structural nets first; this makes later, smaller
    # nets route around the established backbone instead of the reverse.
    return sorted(nets, key=lambda name: (-len(circuit.nets[name].nodes), name))


def _clear_net_geometry(schematic: Schematic, net_names: set[str]) -> None:
    schematic.wires = [wire for wire in schematic.wires if wire.net not in net_names]
    schematic.labels = [label for label in schematic.labels if label.net not in net_names]
    schematic.junctions = [
        junction for junction in schematic.junctions if junction.net not in net_names
    ]


def _positions(schematic: Schematic, references: list[str]) -> dict[str, tuple[float, float]]:
    wanted = set(references)
    result = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in schematic.symbols
        if symbol.reference in wanted
    }
    missing = wanted.difference(result)
    if missing:
        raise KeyError(f"components have no drawable symbol: {', '.join(sorted(missing))}")
    return result


def _validate_symbol_clearance(schematic: Schematic) -> None:
    symbols = list(schematic.symbols)
    for index, left in enumerate(symbols):
        for right in symbols[index + 1 :]:
            dx = abs(left.x - right.x)
            dy = abs(left.y - right.y)
            if dx < _MIN_CENTER_CLEARANCE_MM - _EPS and dy < _MIN_CENTER_CLEARANCE_MM - _EPS:
                raise ValueError(
                    f"components '{left.reference}' and '{right.reference}' are too close"
                )


def _movement_metrics(
    baseline: dict[str, tuple[float, float]],
    trial: Schematic,
) -> tuple[float, int, list[str]]:
    moved: list[str] = []
    distance = 0.0
    trial_positions = _positions(trial, list(baseline))
    for reference, (old_x, old_y) in baseline.items():
        new_x, new_y = trial_positions[reference]
        delta = abs(new_x - old_x) + abs(new_y - old_y)
        if delta > _EPS:
            moved.append(reference)
            distance += delta
    return distance, len(moved), sorted(moved)


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
    baseline_positions: dict[str, tuple[float, float]],
) -> tuple[float, Schematic, dict[str, Any]]:
    """Reroute the neighborhood nets on a copy and return its total visual cost."""
    circuit = session.require_circuit()
    trial = source.model_copy(deep=True)
    impacted_set = set(impacted)
    _validate_symbol_clearance(trial)
    _clear_net_geometry(trial, impacted_set)

    routes = [route_net_incremental(circuit, trial, name) for name in impacted]
    bounds = _candidate_bounds(trial)
    edge_penalty, edge_clearance = _page_clearance(trial, bounds)
    movement_mm, moved_count, moved = _movement_metrics(baseline_positions, trial)
    route_score = sum(float(route["route_score"]) for route in routes)
    route_length = sum(float(route["route_length_mm"]) for route in routes)
    route_bends = sum(int(route["route_bends"]) for route in routes)
    compactness = _compactness(trial)
    total = (
        route_score
        + movement_mm * _MOVEMENT_WEIGHT
        + moved_count * _MOVED_COMPONENT_PENALTY
        + compactness * _COMPACTNESS_WEIGHT
        + edge_penalty
    )
    metrics: dict[str, Any] = {
        "score": round(total, 3),
        "route_score": round(route_score, 3),
        "route_length_mm": round(route_length, 3),
        "route_bends": route_bends,
        "movement_mm": round(movement_mm, 3),
        "moved_components": moved,
        "compactness_span_mm": round(compactness, 3),
        "edge_penalty": round(edge_penalty, 3),
        "edge_clearance_mm": round(edge_clearance, 3) if edge_clearance is not None else None,
        "rerouted_nets": impacted,
    }
    return total, trial, metrics


def _anchors_for(
    session: Session,
    reference: str,
    neighborhood: list[str],
) -> list[str]:
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
    """Compact a small semantic neighborhood while freezing the rest of the sheet.

    The operation is deliberately bounded: at most six electrically related
    components are reconsidered, unrelated component positions never move, and
    only nets touching the selected neighborhood are rerouted. Existing
    ``placement_locked`` properties are preserved; this explicit optimization is
    the controlled exception to the normal single-component freeze rule.
    """
    if passes < 1 or passes > 3:
        raise ValueError("passes must be between 1 and 3")
    if not math.isfinite(min_improvement) or min_improvement < 0:
        raise ValueError("min_improvement must be a non-negative finite number")

    neighborhood = _semantic_neighborhood(session, reference, max_components)
    selected = set(neighborhood)
    impacted = _impacted_nets(session, selected)
    if not impacted:
        raise ValueError("semantic neighborhood has no complete nets to optimize")

    base = session.require_schematic().model_copy(deep=True)
    baseline_positions = _positions(base, neighborhood)
    outside_positions = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in base.symbols
        if symbol.reference not in selected
    }

    baseline_score, best_schematic, baseline_metrics = _score_state(
        session, base, impacted, baseline_positions
    )
    best_score = baseline_score
    history: list[dict[str, Any]] = []
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
                                baseline_positions,
                            )
                        except Exception:
                            continue
                        if score + min_improvement < local_best_score:
                            local_best_score = score
                            local_best = routed
                            local_summary = {
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

    # Hard invariant: nothing outside the selected semantic neighborhood moved.
    final_outside = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in best_schematic.symbols
        if symbol.reference not in selected
    }
    if final_outside != outside_positions:
        raise RuntimeError("neighborhood reflow attempted to move a component outside its boundary")

    final_movement_mm, _count, moved = _movement_metrics(baseline_positions, best_schematic)
    improved = best_score + _EPS < baseline_score
    if improved:
        session.schematic = best_schematic

    return {
        "ok": True,
        "reference": reference,
        "neighborhood": neighborhood,
        "rerouted_nets": impacted,
        "improved": improved,
        "baseline_score": round(baseline_score, 3),
        "score": round(best_score, 3),
        "score_improvement": round(max(0.0, baseline_score - best_score), 3),
        "movement_mm": round(final_movement_mm if improved else 0.0, 3),
        "moved_components": moved if improved else [],
        "baseline": baseline_metrics,
        "accepted_moves": history,
        "outside_components_frozen": True,
        "pending_commit": improved,
    }

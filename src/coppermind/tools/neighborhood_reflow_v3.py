"""Lexicographic target-bridge reflow for dense incremental schematics.

V3 proved that target-first search is safe, but freezing every non-focus net can
turn accepted wires into walls and keep a late bridge component stranded.  This
revision keeps all component positions except the target frozen, but allows the
small semantic neighborhood's nets to reroute while evaluating target slots.
Candidates are chosen lexicographically: shorten the target's own nets first,
then minimize total rerouted length, bends and movement.
"""

from __future__ import annotations

from typing import Any

from coppermind.session import Session
from coppermind.tools.neighborhood_reflow import (
    _impacted_nets,
    _positions,
    _semantic_neighborhood,
)
from coppermind.tools.neighborhood_reflow_v2 import (
    _focus_nets,
    _local_slot_points,
    _move_symbol_to,
    _score_state,
    _symbol_position,
)

_EPS = 1e-6
_MIN_GRID_GAIN_MM = 5.08
_MAX_REQUIRED_GAIN_MM = 25.4
_ROUTE_SLACK_MM = 50.8
_ROUTE_SLACK_RATIO = 0.20


def _minimum_focus_gain(baseline_focus_length: float, min_improvement: float) -> float:
    """Require visible compaction without making small circuits impossible."""
    proportional = max(_MIN_GRID_GAIN_MM, baseline_focus_length * 0.15)
    requested = max(_MIN_GRID_GAIN_MM, min_improvement * _MIN_GRID_GAIN_MM)
    return min(_MAX_REQUIRED_GAIN_MM, max(proportional, requested))


def _target_key(
    metrics: dict[str, Any],
    target_from: tuple[float, float],
    target_to: tuple[float, float],
) -> tuple[float, float, int, float, float]:
    """Prefer focus-net compaction before every secondary visual objective."""
    movement = abs(target_to[0] - target_from[0]) + abs(target_to[1] - target_from[1])
    return (
        float(metrics["focus_route_length_mm"]),
        float(metrics["route_length_mm"]),
        int(metrics["route_bends"]),
        movement,
        float(metrics["score"]),
    )


def component_reflow_neighborhood(
    session: Session,
    reference: str,
    max_components: int = 4,
    passes: int = 2,
    gap_mm: float = 25.4,
    min_improvement: float = 1.0,
) -> dict:
    """Compact a late bridge component while rerouting only its semantic neighborhood.

    ``passes`` and ``gap_mm`` remain part of the routed-tool schema for backward
    compatibility.  This revision deliberately moves only the target component;
    every other component is a hard positional invariant.  Nets touching the
    bounded semantic neighborhood may reroute so previously accepted wires do
    not become artificial walls around the target.
    """
    if passes < 1 or passes > 3:
        raise ValueError("passes must be between 1 and 3")
    if gap_mm < 2.54 or gap_mm > 101.6:
        raise ValueError("gap_mm must be between 2.54 and 101.6")
    if min_improvement < 0:
        raise ValueError("min_improvement must be non-negative")

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
    target_from = baseline_positions[reference]
    frozen_positions = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in base.symbols
        if symbol.reference != reference
    }

    baseline_score, _baseline_routed, baseline_metrics = _score_state(
        session,
        base,
        impacted,
        focus,
        baseline_positions,
    )
    baseline_focus = float(baseline_metrics["focus_route_length_mm"])
    baseline_total = float(baseline_metrics["route_length_mm"])
    required_gain = _minimum_focus_gain(baseline_focus, min_improvement)
    total_route_limit = baseline_total + max(_ROUTE_SLACK_MM, baseline_total * _ROUTE_SLACK_RATIO)

    best_schematic = None
    best_metrics: dict[str, Any] | None = None
    best_key: tuple[float, float, int, float, float] | None = None
    evaluated = 0
    routable = 0

    # The V2 candidate generator already seeds the focus-neighbour median and a
    # dense local grid.  Here each candidate reroutes *all* neighborhood nets,
    # but never moves another symbol.  This lets VOUT/GND bend around a compact
    # VIN/SENSE bridge instead of acting as permanent walls.
    for x, y in _local_slot_points(session, base, reference, neighborhood, focus):
        evaluated += 1
        candidate = base.model_copy(deep=True)
        try:
            _move_symbol_to(candidate, reference, x, y)
            score, routed, metrics = _score_state(
                session,
                candidate,
                impacted,
                focus,
                baseline_positions,
            )
        except Exception:
            continue
        routable += 1

        focus_length = float(metrics["focus_route_length_mm"])
        total_length = float(metrics["route_length_mm"])
        focus_gain = baseline_focus - focus_length
        if focus_gain + _EPS < required_gain:
            continue
        if total_length > total_route_limit + _EPS:
            continue

        target_to = _symbol_position(routed, reference)
        key = _target_key(metrics, target_from, target_to)
        if best_key is None or key < best_key:
            best_key = key
            best_schematic = routed
            best_metrics = metrics

    if best_schematic is None or best_metrics is None:
        return {
            "ok": True,
            "reference": reference,
            "strategy": "lexicographic-target-bridge",
            "neighborhood": neighborhood,
            "focus_nets": sorted(focus),
            "rerouted_nets": impacted,
            "improved": False,
            "baseline_score": round(baseline_score, 3),
            "score": round(baseline_score, 3),
            "baseline_focus_route_length_mm": round(baseline_focus, 3),
            "focus_route_length_mm": round(baseline_focus, 3),
            "focus_route_gain_mm": 0.0,
            "required_focus_gain_mm": round(required_gain, 3),
            "target_from": {"x": target_from[0], "y": target_from[1]},
            "target_to": {"x": target_from[0], "y": target_from[1]},
            "target_slot_candidates": evaluated,
            "routable_candidates": routable,
            "outside_components_frozen": True,
            "pending_commit": False,
            "baseline": baseline_metrics,
        }

    final_frozen = {
        symbol.reference: (symbol.x, symbol.y)
        for symbol in best_schematic.symbols
        if symbol.reference != reference
    }
    if final_frozen != frozen_positions:
        raise RuntimeError("target bridge reflow attempted to move a non-target component")

    target_to = _symbol_position(best_schematic, reference)
    final_focus = float(best_metrics["focus_route_length_mm"])
    final_total = float(best_metrics["route_length_mm"])
    focus_gain = baseline_focus - final_focus
    session.schematic = best_schematic

    return {
        "ok": True,
        "reference": reference,
        "strategy": "lexicographic-target-bridge",
        "neighborhood": neighborhood,
        "focus_nets": sorted(focus),
        "rerouted_nets": impacted,
        "improved": True,
        "baseline_score": round(baseline_score, 3),
        "score": round(float(best_metrics["score"]), 3),
        "score_improvement": round(baseline_score - float(best_metrics["score"]), 3),
        "baseline_focus_route_length_mm": round(baseline_focus, 3),
        "focus_route_length_mm": round(final_focus, 3),
        "focus_route_gain_mm": round(focus_gain, 3),
        "required_focus_gain_mm": round(required_gain, 3),
        "baseline_route_length_mm": round(baseline_total, 3),
        "route_length_mm": round(final_total, 3),
        "route_length_delta_mm": round(final_total - baseline_total, 3),
        "route_length_limit_mm": round(total_route_limit, 3),
        "target_from": {"x": target_from[0], "y": target_from[1]},
        "target_to": {"x": target_to[0], "y": target_to[1]},
        "movement_mm": round(
            abs(target_to[0] - target_from[0]) + abs(target_to[1] - target_from[1]), 3
        ),
        "moved_components": [reference],
        "target_slot_candidates": evaluated,
        "routable_candidates": routable,
        "outside_components_frozen": True,
        "pending_commit": True,
        "baseline": baseline_metrics,
        "final": best_metrics,
    }

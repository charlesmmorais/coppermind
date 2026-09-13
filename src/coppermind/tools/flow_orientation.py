"""Automatic schematic component orientation driven by electrical flow.

This module complements cost-based placement. Placement decides *where* a
component belongs; flow orientation decides *which way it should face* once its
semantic nets are known. Candidate rotations are evaluated on isolated
schematic snapshots and only the target component plus its impacted-net geometry
may change.
"""

from __future__ import annotations

import math
from typing import Any

from coppermind.circuit import Circuit
from coppermind.schematic.composer import _pin_anchor, symbol_pin_geometry
from coppermind.schematic.incremental import _foreign_pin_contacts, route_net_incremental
from coppermind.schematic.models import Schematic
from coppermind.session import Session
from coppermind.tools.auto_placement import _component_place_auto, _page_clearance
from coppermind.serialize.kicad_sch import (
    _boxes_overlap,
    _field_layout,
    _symbol_body_box,
    _text_box,
    _wire_intersects_box,
)

_ROTATIONS = (0.0, 90.0, 180.0, 270.0)
_AXIS_MISMATCH_PENALTY = 12.7
_SINGLE_PIN_AXIS_MISMATCH_PENALTY = 6.35
_BEND_PENALTY_MM = 2.54
_FLOW_DISTANCE_WEIGHT = 0.20
_EPS = 1e-6


def _normalized_rotation(value: float) -> float:
    normalized = value % 360.0
    return 0.0 if math.isclose(normalized, 360.0, abs_tol=_EPS) else normalized


def _impacted_nets(circuit: Circuit, reference: str) -> list[str]:
    return sorted(
        name
        for name, net in circuit.nets.items()
        if len(net.nodes) >= 2 and any(node.component == reference for node in net.nodes)
    )


def _clear_impacted_geometry(schematic: Schematic, impacted: set[str]) -> None:
    schematic.wires = [wire for wire in schematic.wires if wire.net not in impacted]
    schematic.labels = [label for label in schematic.labels if label.net not in impacted]
    schematic.junctions = [
        junction for junction in schematic.junctions if junction.net not in impacted
    ]


def _target_symbol(schematic: Schematic, reference: str):
    symbol = next((item for item in schematic.symbols if item.reference == reference), None)
    if symbol is None:
        raise KeyError(f"schematic symbol '{reference}' does not exist")
    return symbol


def _visible_pin_numbers(schematic: Schematic, reference: str) -> list[str]:
    symbol = _target_symbol(schematic, reference)
    library = schematic.library_symbols.get(symbol.lib_id)
    if library is None:
        raise KeyError(f"resolved library symbol '{symbol.lib_id}' is unavailable")
    return sorted(symbol_pin_geometry(library, symbol.unit))


def _pin_net_map(circuit: Circuit, reference: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for net_name, net in circuit.nets.items():
        for node in net.nodes:
            if node.component == reference:
                result[node.pin] = net_name
    return result


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _foreign_centroid_for_pin(
    circuit: Circuit,
    schematic: Schematic,
    reference: str,
    pin_number: str,
    net_name: str,
) -> tuple[float, float] | None:
    net = circuit.nets.get(net_name)
    if net is None:
        return None
    points: list[tuple[float, float]] = []
    for node in net.nodes:
        if node.component == reference and node.pin == pin_number:
            continue
        anchor = _pin_anchor(schematic, node.component, node.pin)
        if anchor is not None:
            points.append(anchor)
    return _centroid(points)


def _display_axis(schematic: Schematic, reference: str, pin_numbers: list[str]) -> str | None:
    if len(pin_numbers) < 2:
        return None
    first = _pin_anchor(schematic, reference, pin_numbers[0])
    second = _pin_anchor(schematic, reference, pin_numbers[1])
    if first is None or second is None:
        return None
    dx = abs(first[0] - second[0])
    dy = abs(first[1] - second[1])
    if math.isclose(dx, dy, abs_tol=_EPS):
        return None
    return "horizontal" if dx > dy else "vertical"


def _preferred_axis(
    schematic: Schematic,
    reference: str,
    pin_centroids: dict[str, tuple[float, float]],
) -> str | None:
    if len(pin_centroids) >= 2:
        ordered = sorted(pin_centroids)
        first = pin_centroids[ordered[0]]
        second = pin_centroids[ordered[1]]
        dx = abs(first[0] - second[0])
        dy = abs(first[1] - second[1])
        if math.isclose(dx, dy, abs_tol=_EPS):
            return None
        return "horizontal" if dx > dy else "vertical"

    if len(pin_centroids) == 1:
        symbol = _target_symbol(schematic, reference)
        centroid = next(iter(pin_centroids.values()))
        dx = abs(centroid[0] - symbol.x)
        dy = abs(centroid[1] - symbol.y)
        if math.isclose(dx, dy, abs_tol=_EPS):
            return None
        return "horizontal" if dx > dy else "vertical"
    return None


def _flow_metrics(
    circuit: Circuit,
    schematic: Schematic,
    reference: str,
) -> dict[str, Any]:
    pin_numbers = _visible_pin_numbers(schematic, reference)
    pin_nets = _pin_net_map(circuit, reference)
    pin_centroids: dict[str, tuple[float, float]] = {}
    direct_distance = 0.0

    for pin_number in pin_numbers:
        net_name = pin_nets.get(pin_number)
        if net_name is None:
            continue
        centroid = _foreign_centroid_for_pin(
            circuit,
            schematic,
            reference,
            pin_number,
            net_name,
        )
        anchor = _pin_anchor(schematic, reference, pin_number)
        if centroid is None or anchor is None:
            continue
        pin_centroids[pin_number] = centroid
        direct_distance += abs(anchor[0] - centroid[0]) + abs(anchor[1] - centroid[1])

    displayed = _display_axis(schematic, reference, pin_numbers)
    preferred = _preferred_axis(schematic, reference, pin_centroids)
    mismatch_penalty = 0.0
    if displayed is not None and preferred is not None and displayed != preferred:
        mismatch_penalty = (
            _AXIS_MISMATCH_PENALTY if len(pin_centroids) >= 2 else _SINGLE_PIN_AXIS_MISMATCH_PENALTY
        )

    return {
        "pin_centroids": {
            pin: {"x": round(point[0], 3), "y": round(point[1], 3)}
            for pin, point in pin_centroids.items()
        },
        "flow_distance_mm": round(direct_distance, 3),
        "display_axis": displayed,
        "preferred_axis": preferred,
        "axis_mismatch_penalty": mismatch_penalty,
    }


def _flow_layout_cost(circuit: Circuit, schematic: Schematic, reference: str) -> dict[str, Any]:
    """Score flow and displayed field clearance on the routed candidate."""
    contacts = _foreign_pin_contacts(circuit, schematic)
    if contacts:
        raise ValueError(f"candidate creates FOREIGN_PIN_GEOMETRY_CONTACT: {contacts}")
    flow = _flow_metrics(circuit, schematic, reference)
    target_fields: list[tuple[float, float, float, float]] = []
    other_fields: list[tuple[float, float, float, float]] = []
    bodies = []
    for symbol in schematic.symbols:
        library = schematic.library_symbols[symbol.lib_id]
        body = _symbol_body_box(symbol, library)
        bodies.append(body)
        fields = _field_layout(symbol, library)
        for name, text in (("Reference", symbol.reference), ("Value", symbol.value)):
            x, y, _, hidden, justify = fields[name]
            if text and not hidden:
                box = _text_box(text, x, y, justify)
                (target_fields if symbol.reference == reference else other_fields).append(box)
    boxes = bodies + target_fields + other_fields
    bounds = (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
    _page_clearance(schematic, bounds)
    collisions = sum(_boxes_overlap(a, b) for a in target_fields for b in bodies + other_fields)
    collisions += sum(_wire_intersects_box(w, b) for b in target_fields for w in schematic.wires)
    field_penalty = 25.4 * collisions
    return {
        **flow,
        "field_collision_penalty": field_penalty,
        "extra_score": float(flow["flow_distance_mm"]) * _FLOW_DISTANCE_WEIGHT
        + float(flow["axis_mismatch_penalty"])
        + field_penalty,
    }


def _evaluate_rotation(
    circuit: Circuit,
    base: Schematic,
    reference: str,
    rotation: float,
    impacted: list[str],
) -> tuple[Schematic, dict[str, Any]]:
    trial = base.model_copy(deep=True)
    target = _target_symbol(trial, reference)
    target.rotation = _normalized_rotation(rotation)
    impacted_set = set(impacted)
    _clear_impacted_geometry(trial, impacted_set)

    routes = [route_net_incremental(circuit, trial, net_name) for net_name in impacted]
    route_length = sum(float(item.get("route_length_mm", 0.0)) for item in routes)
    route_score = sum(float(item.get("route_score", 0.0)) for item in routes)
    route_bends = sum(int(item.get("route_bends", 0)) for item in routes)
    flow = _flow_layout_cost(circuit, trial, reference)
    total = route_score + route_bends * _BEND_PENALTY_MM + float(flow["extra_score"])
    return trial, {
        "rotation": target.rotation,
        "score": round(total, 3),
        "route_score": round(route_score, 3),
        "route_length_mm": round(route_length, 3),
        "route_bends": route_bends,
        **flow,
    }


def choose_flow_orientation(
    circuit: Circuit,
    schematic: Schematic,
    reference: str,
) -> tuple[Schematic, dict[str, Any]]:
    """Return a copy with the best legal 90-degree orientation for one symbol."""
    target = _target_symbol(schematic, reference)
    if target.lib_id.lower().startswith("power:"):
        return schematic.model_copy(deep=True), {
            "reference": reference,
            "changed": False,
            "reason": "power symbols keep their conventional orientation",
            "rotation": target.rotation,
            "candidates": [],
        }

    pin_numbers = _visible_pin_numbers(schematic, reference)
    if len(pin_numbers) < 2:
        return schematic.model_copy(deep=True), {
            "reference": reference,
            "changed": False,
            "reason": "fewer than two visible pins",
            "rotation": target.rotation,
            "candidates": [],
        }

    impacted = _impacted_nets(circuit, reference)
    if not impacted:
        return schematic.model_copy(deep=True), {
            "reference": reference,
            "changed": False,
            "reason": "component has no complete semantic nets",
            "rotation": target.rotation,
            "candidates": [],
        }

    current = _normalized_rotation(target.rotation)
    candidates: list[tuple[tuple[float, int, int], Schematic, dict[str, Any]]] = []
    summaries: list[dict[str, Any]] = []
    for rank, rotation in enumerate(_ROTATIONS):
        try:
            trial, summary = _evaluate_rotation(
                circuit,
                schematic,
                reference,
                rotation,
                impacted,
            )
            summary["ok"] = True
            summaries.append(summary)
            keep_current_rank = 0 if math.isclose(rotation, current, abs_tol=_EPS) else 1
            candidates.append(((float(summary["score"]), keep_current_rank, rank), trial, summary))
        except Exception as exc:
            summaries.append({"rotation": rotation, "ok": False, "error": str(exc)})

    if not candidates:
        errors = "; ".join(
            f"{item['rotation']}°: {item.get('error', 'rejected')}" for item in summaries
        )
        raise RuntimeError(f"no legal flow orientation for '{reference}'; candidates: {errors}")

    _, best_schematic, best = min(candidates, key=lambda item: item[0])
    changed = not math.isclose(float(best["rotation"]), current, abs_tol=_EPS)
    return best_schematic, {
        "reference": reference,
        "changed": changed,
        "from_rotation": current,
        "rotation": best["rotation"],
        "display_axis": best.get("display_axis"),
        "preferred_axis": best.get("preferred_axis"),
        "score": best["score"],
        "route_length_mm": best["route_length_mm"],
        "route_bends": best["route_bends"],
        "flow_distance_mm": best["flow_distance_mm"],
        "rerouted_nets": impacted,
        "candidates": summaries,
    }


def component_orient_flow(
    session: Session,
    reference: str,
    lock: bool = True,
    force: bool = False,
) -> dict:
    """Orient one schematic component to follow the local electrical flow."""
    circuit = session.require_circuit()
    if reference not in circuit.components:
        raise KeyError(f"component '{reference}' does not exist")
    component = circuit.components[reference]
    if component.properties.get("orientation_locked") == "true" and not force:
        raise ValueError(
            f"component '{reference}' orientation is locked; pass force=true to reevaluate it"
        )

    oriented, result = choose_flow_orientation(
        circuit,
        session.require_schematic(),
        reference,
    )
    session.schematic = oriented
    if lock:
        component.properties["orientation_locked"] = "true"
    elif force:
        component.properties.pop("orientation_locked", None)
    result["locked"] = component.properties.get("orientation_locked") == "true"
    result["pending_commit"] = True
    return result


def component_place_flow(
    session: Session,
    reference: str,
    anchor: str,
    gap_mm: float = 25.4,
    directions: list[str] | None = None,
    lock: bool = True,
    force: bool = False,
) -> dict:
    """Jointly choose position and rotation without changing accepted neighbours.

    An explicit direction is relative to the requested anchor. It must not be
    silently reinterpreted against a different component (the R3 backtracking
    regression). The shared placement engine scores each position x rotation
    on an isolated snapshot and commits only the final legal candidate.
    """
    circuit = session.require_circuit()
    component = circuit.components[reference]
    if component.properties.get("orientation_locked") == "true" and not force:
        raise ValueError(
            f"component '{reference}' orientation is locked; pass force=true to reevaluate it"
        )
    symbol = _target_symbol(session.require_schematic(), reference)
    rotations = (symbol.rotation,) if symbol.lib_id.lower().startswith("power:") else _ROTATIONS
    placement = _component_place_auto(
        session,
        reference,
        anchor,
        gap_mm,
        directions,
        lock,
        force,
        rotations=rotations,
        candidate_cost=_flow_layout_cost,
        anchor_only=directions is not None,
    )
    if lock:
        component.properties["orientation_locked"] = "true"
    elif force:
        component.properties.pop("orientation_locked", None)
    best = placement["chosen_metrics"]
    orientation = {
        **best,
        "reference": reference,
        "from_rotation": symbol.rotation,
        "changed": not math.isclose(best["rotation"], symbol.rotation, abs_tol=_EPS),
        "locked": component.properties.get("orientation_locked") == "true",
        "pending_commit": True,
    }
    return {
        "ok": True,
        "reference": reference,
        "placement": placement,
        "orientation": orientation,
        "chosen_rotation": best["rotation"],
        "flow_axis": best.get("display_axis"),
        "rerouted_nets": placement["rerouted_nets"],
        "pending_commit": True,
    }

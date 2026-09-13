"""Flow-aware orientation for incremental schematic authoring.

Placement and orientation are deliberately separated. The existing local
placer chooses a legal position; this module then evaluates KiCad quarter-turn
orientations at that fixed position, reroutes only the component's impacted
semantic nets, and prefers the rotation whose pin directions follow the
surrounding electrical flow with the lowest routing cost.
"""

from __future__ import annotations

import math
from typing import Any

from coppermind.circuit import Circuit
from coppermind.schematic.composer import _pin_anchor
from coppermind.schematic.incremental import route_net_incremental
from coppermind.schematic.models import Schematic
from coppermind.session import Session
from coppermind.tools.auto_placement import (
    _clear_impacted_geometry,
    _impacted_nets,
    component_place_auto,
)

_ROTATIONS = (0.0, 90.0, 180.0, 270.0)
_FLOW_WEIGHT_MM = 12.7
_ROTATION_CHANGE_PENALTY = 0.25
_EPS = 1e-6


def _symbol_by_ref(schematic: Schematic, reference: str):
    return next((item for item in schematic.symbols if item.reference == reference), None)


def _normalize_rotation(value: float) -> float:
    normalized = float(value) % 360.0
    if math.isclose(normalized, 360.0, abs_tol=_EPS):
        return 0.0
    return normalized


def _normalize_rotations(rotations: list[float] | None) -> list[float]:
    raw = list(_ROTATIONS) if rotations is None else rotations
    result: list[float] = []
    for value in raw:
        if not math.isfinite(value):
            raise ValueError("rotation candidates must be finite")
        normalized = _normalize_rotation(value)
        quarter = round(normalized / 90.0)
        snapped = float((quarter * 90) % 360)
        if not math.isclose(normalized, snapped, abs_tol=_EPS):
            raise ValueError("rotation candidates must be multiples of 90 degrees")
        if snapped not in result:
            result.append(snapped)
    if not result:
        raise ValueError("rotations must contain at least one candidate")
    return result


def _angular_quarter_turns(left: float, right: float) -> int:
    delta = abs(_normalize_rotation(left) - _normalize_rotation(right))
    delta = min(delta, 360.0 - delta)
    return int(round(delta / 90.0))


def _other_endpoint_points(
    circuit: Circuit,
    schematic: Schematic,
    reference: str,
    net_name: str,
) -> list[tuple[float, float]]:
    """Return electrical endpoint anchors belonging to other components on a net."""
    net = circuit.nets.get(net_name)
    if net is None:
        return []
    points: list[tuple[float, float]] = []
    for node in net.nodes:
        if node.component == reference:
            continue
        anchor = _pin_anchor(schematic, node.component, node.pin)
        if anchor is not None:
            points.append(anchor)
            continue
        symbol = _symbol_by_ref(schematic, node.component)
        if symbol is not None:
            points.append((symbol.x, symbol.y))
    return points


def _flow_alignment_penalty(
    circuit: Circuit,
    schematic: Schematic,
    reference: str,
) -> tuple[float, list[dict[str, Any]]]:
    """Penalize pins that point away from the semantic neighbours of their net."""
    symbol = _symbol_by_ref(schematic, reference)
    if symbol is None:
        raise KeyError(f"schematic symbol '{reference}' does not exist")

    total = 0.0
    observations: list[dict[str, Any]] = []
    for net_name, net in circuit.nets.items():
        own_nodes = [node for node in net.nodes if node.component == reference]
        if not own_nodes:
            continue
        targets = _other_endpoint_points(circuit, schematic, reference, net_name)
        if not targets:
            continue
        target_x = sum(x for x, _ in targets) / len(targets)
        target_y = sum(y for _, y in targets) / len(targets)
        toward_x = target_x - symbol.x
        toward_y = target_y - symbol.y
        toward_norm = math.hypot(toward_x, toward_y)
        if toward_norm <= _EPS:
            continue

        for node in own_nodes:
            anchor = _pin_anchor(schematic, reference, node.pin)
            if anchor is None:
                continue
            pin_x = anchor[0] - symbol.x
            pin_y = anchor[1] - symbol.y
            pin_norm = math.hypot(pin_x, pin_y)
            if pin_norm <= _EPS:
                continue
            cosine = (pin_x * toward_x + pin_y * toward_y) / (pin_norm * toward_norm)
            cosine = max(-1.0, min(1.0, cosine))
            penalty = (1.0 - cosine) * _FLOW_WEIGHT_MM
            total += penalty
            observations.append(
                {
                    "net": net_name,
                    "pin": node.pin,
                    "cosine": round(cosine, 4),
                    "penalty": round(penalty, 3),
                    "target": {"x": round(target_x, 3), "y": round(target_y, 3)},
                }
            )
    return total, observations


def _evaluate_rotation(
    circuit: Circuit,
    base: Schematic,
    reference: str,
    rotation: float,
    impacted: list[str],
    current_rotation: float,
) -> tuple[float, Schematic, dict[str, Any]]:
    trial = base.model_copy(deep=True)
    symbol = _symbol_by_ref(trial, reference)
    if symbol is None:
        raise KeyError(f"schematic symbol '{reference}' does not exist")
    symbol.rotation = rotation

    impacted_set = set(impacted)
    _clear_impacted_geometry(trial, impacted_set)
    routes = [route_net_incremental(circuit, trial, net_name) for net_name in impacted]
    flow_penalty, flow = _flow_alignment_penalty(circuit, trial, reference)
    route_score = sum(float(item.get("route_score", 0.0)) for item in routes)
    route_length = sum(float(item.get("route_length_mm", 0.0)) for item in routes)
    route_bends = sum(int(item.get("route_bends", 0)) for item in routes)
    rotation_penalty = _angular_quarter_turns(current_rotation, rotation) * _ROTATION_CHANGE_PENALTY
    total = route_score + flow_penalty + rotation_penalty
    return total, trial, {
        "rotation": rotation,
        "score": round(total, 3),
        "route_score": round(route_score, 3),
        "route_length_mm": round(route_length, 3),
        "route_bends": route_bends,
        "flow_penalty": round(flow_penalty, 3),
        "rotation_change_penalty": round(rotation_penalty, 3),
        "flow": flow,
        "rerouted_nets": impacted,
    }


def component_orient_auto(
    session: Session,
    reference: str,
    rotations: list[float] | None = None,
    lock: bool = True,
    force: bool = False,
) -> dict:
    """Choose a 0/90/180/270 orientation from routing cost and electrical flow."""
    circuit = session.require_circuit()
    if reference not in circuit.components:
        raise KeyError(f"component '{reference}' does not exist")
    component = circuit.components[reference]
    if component.properties.get("orientation_locked") == "true" and not force:
        raise ValueError(
            f"component '{reference}' orientation is locked; pass force=true to re-orient it"
        )

    base = session.require_schematic().model_copy(deep=True)
    symbol = _symbol_by_ref(base, reference)
    if symbol is None:
        raise KeyError(f"component '{reference}' has no drawable symbol")
    current_rotation = _normalize_rotation(symbol.rotation)
    impacted = _impacted_nets(session, reference)
    if not impacted:
        raise ValueError(
            f"component '{reference}' has no complete semantic net; declare connectivity before auto orientation"
        )

    evaluated: list[dict[str, Any]] = []
    successful: list[tuple[tuple[float, float, int, float], Schematic, dict[str, Any]]] = []
    for rotation in _normalize_rotations(rotations):
        try:
            total, trial, summary = _evaluate_rotation(
                circuit,
                base,
                reference,
                rotation,
                impacted,
                current_rotation,
            )
            evaluated.append({"ok": True, **summary})
            successful.append(
                (
                    (
                        total,
                        float(summary["flow_penalty"]),
                        int(summary["route_bends"]),
                        rotation,
                    ),
                    trial,
                    summary,
                )
            )
        except Exception as exc:
            evaluated.append({"ok": False, "rotation": rotation, "error": str(exc)})

    if not successful:
        errors = "; ".join(
            f"{item['rotation']}°: {item.get('error', 'rejected')}" for item in evaluated
        )
        raise RuntimeError(f"no legal automatic orientation for '{reference}'; {errors}")

    _, best_schematic, best = min(successful, key=lambda item: item[0])
    session.schematic = best_schematic
    if lock:
        component.properties["orientation_locked"] = "true"
    elif force:
        component.properties.pop("orientation_locked", None)

    return {
        "ok": True,
        "reference": reference,
        "from_rotation": current_rotation,
        "chosen_rotation": best["rotation"],
        "score": best["score"],
        "route_score": best["route_score"],
        "route_length_mm": best["route_length_mm"],
        "route_bends": best["route_bends"],
        "flow_penalty": best["flow_penalty"],
        "flow": best["flow"],
        "rerouted_nets": impacted,
        "locked": component.properties.get("orientation_locked") == "true",
        "candidates": evaluated,
        "pending_commit": True,
    }


def component_place_flow_auto(
    session: Session,
    reference: str,
    anchor: str,
    gap_mm: float = 25.4,
    directions: list[str] | None = None,
    rotations: list[float] | None = None,
    lock: bool = True,
    force: bool = False,
) -> dict:
    """Automatically choose local position, quarter-turn orientation, and rerouting."""
    circuit = session.require_circuit()
    if reference not in circuit.components:
        raise KeyError(f"component '{reference}' does not exist")
    component = circuit.components[reference]
    schematic_before = session.require_schematic().model_copy(deep=True)
    properties_before = dict(component.properties)

    try:
        placement = component_place_auto(
            session,
            reference,
            anchor,
            gap_mm=gap_mm,
            directions=directions,
            lock=False,
            force=force,
        )
        orientation = component_orient_auto(
            session,
            reference,
            rotations=rotations,
            lock=False,
            force=force,
        )
    except Exception:
        session.schematic = schematic_before
        component.properties.clear()
        component.properties.update(properties_before)
        raise

    if lock:
        component.properties["placement_locked"] = "true"
        component.properties["orientation_locked"] = "true"
    elif force:
        component.properties.pop("placement_locked", None)
        component.properties.pop("orientation_locked", None)

    return {
        "ok": True,
        "reference": reference,
        "anchor": anchor,
        "placement": placement,
        "orientation": orientation,
        "chosen_position": placement.get("to"),
        "chosen_rotation": orientation.get("chosen_rotation"),
        "flow_penalty": orientation.get("flow_penalty"),
        "route_length_mm": orientation.get("route_length_mm"),
        "rerouted_nets": orientation.get("rerouted_nets", []),
        "placement_locked": component.properties.get("placement_locked") == "true",
        "orientation_locked": component.properties.get("orientation_locked") == "true",
        "pending_commit": True,
    }

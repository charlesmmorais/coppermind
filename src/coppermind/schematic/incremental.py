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
    _route_net,
)
from coppermind.schematic.erc import run_kicad_erc
from coppermind.schematic.models import Schematic
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


def _snap(value: float) -> float:
    return round(value / _GRID) * _GRID


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

    wires, label, junctions = _route_net(net_name, endpoints)
    for wire in wires:
        wire.net = net_name
    label.net = net_name
    for junction in junctions:
        junction.net = net_name

    schematic.wires = [wire for wire in schematic.wires if wire.net != net_name]
    schematic.labels = [item for item in schematic.labels if item.net != net_name]
    schematic.junctions = [item for item in schematic.junctions if item.net != net_name]

    schematic.wires.extend(wires)
    if not _net_has_named_power_symbol(circuit, net_name):
        schematic.labels.append(label)
    schematic.junctions.extend(junctions)

    return {
        "net": net_name,
        "pins": [node.key() for node in net.nodes],
        "wires": len(wires),
        "labels": 0 if _net_has_named_power_symbol(circuit, net_name) else 1,
        "junctions": len(junctions),
    }


def _owned_geometry_nets(schematic: Schematic) -> set[str]:
    return {
        item.net
        for item in (*schematic.wires, *schematic.labels, *schematic.junctions)
        if item.net
    }


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

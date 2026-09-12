"""Visual review and geometry-only optimization for composed KiCad schematics.

Electrical intent always remains in Circuit IR.  This module may score and move
symbols, then rebuild wires/labels/junctions, but it never creates components,
nets, pins, PWR_FLAGs or other semantic electrical changes.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from coppermind.circuit import Circuit, ElectricalType
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import symbol_pin_geometry
from coppermind.schematic.erc import evaluate_schematic, run_kicad_erc
from coppermind.schematic.models import Junction, NetLabel, Schematic, SchSymbol, Wire
from coppermind.serialize.kicad_sch import schematic_to_kicad_sch

_GRID = 2.54
_DEFAULT_TARGET_SCORE = 85.0
_BLOCKING_SCORE = 65.0


@dataclass(frozen=True)
class VisualFinding:
    code: str
    severity: str
    message: str
    penalty: float
    refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "penalty": self.penalty,
            "refs": list(self.refs),
        }


class VisualReviewProvider(Protocol):
    """Optional multimodal reviewer over SVG pages produced by KiCad."""

    def review(self, svg_pages: list[str], context: dict[str, Any]) -> list[VisualFinding]: ...


def _snap(value: float) -> float:
    return round(value / _GRID) * _GRID


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)


def _symbol_bounds(schematic: Schematic, symbol: SchSymbol) -> tuple[float, float, float, float]:
    library = schematic.library_symbols.get(symbol.lib_id)
    points: list[tuple[float, float]] = []
    if library is not None:
        for pin in symbol_pin_geometry(library, symbol.unit).values():
            dx, dy = _rotate(pin.x, pin.y, symbol.rotation)
            points.append((symbol.x + dx, symbol.y + dy))
    if not points:
        points = [(symbol.x - 5.08, symbol.y - 5.08), (symbol.x + 5.08, symbol.y + 5.08)]
    margin = 3.81
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _box_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def _wire_crossings(schematic: Schematic) -> list[tuple[int, int]]:
    """Return interior orthogonal crossings that have no explicit junction."""
    junctions = {(_snap(item.x), _snap(item.y)) for item in schematic.junctions}
    result: list[tuple[int, int]] = []
    for i, left in enumerate(schematic.wires):
        left_h = math.isclose(left.y1, left.y2)
        left_v = math.isclose(left.x1, left.x2)
        if not (left_h or left_v):
            continue
        for j, right in enumerate(schematic.wires[i + 1 :], start=i + 1):
            right_h = math.isclose(right.y1, right.y2)
            right_v = math.isclose(right.x1, right.x2)
            if left_h == right_h or left_v == right_v:
                continue
            horizontal = left if left_h else right
            vertical = right if left_h else left
            px, py = vertical.x1, horizontal.y1
            hx0, hx1 = sorted((horizontal.x1, horizontal.x2))
            vy0, vy1 = sorted((vertical.y1, vertical.y2))
            if hx0 < px < hx1 and vy0 < py < vy1 and (_snap(px), _snap(py)) not in junctions:
                result.append((i, j))
    return result


def _flow_reversals(circuit: Circuit | None, schematic: Schematic) -> list[tuple[str, str, str]]:
    if circuit is None:
        return []
    x_by_ref = {symbol.reference: symbol.x for symbol in schematic.symbols}
    source_types = {ElectricalType.OUTPUT, ElectricalType.POWER_OUTPUT, ElectricalType.OPEN_COLLECTOR}
    sink_types = {ElectricalType.INPUT, ElectricalType.POWER_INPUT}
    result: list[tuple[str, str, str]] = []
    for net in circuit.nets.values():
        sources: list[str] = []
        sinks: list[str] = []
        for node in net.nodes:
            component = circuit.components.get(node.component)
            if component is None or node.pin not in component.pins:
                continue
            electrical_type = component.pins[node.pin].electrical_type
            if electrical_type in source_types:
                sources.append(node.component)
            elif electrical_type in sink_types:
                sinks.append(node.component)
        for source in sources:
            for sink in sinks:
                if source in x_by_ref and sink in x_by_ref and x_by_ref[source] > x_by_ref[sink]:
                    result.append((net.name, source, sink))
    return result


def render_schematic_svg(
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    executable: str = "kicad-cli",
    include_svg: bool = False,
) -> dict[str, Any]:
    """Render the generated schematic through KiCad's real SVG exporter."""
    cli = shutil.which(executable)
    if cli is None:
        return {"available": False, "pages": [], "error": f"{executable} not found"}

    with tempfile.TemporaryDirectory(prefix="coppermind-visual-") as tmp:
        root = Path(tmp)
        sch_path = root / f"{schematic.name}.kicad_sch"
        out_dir = root / "svg"
        out_dir.mkdir()
        sch_path.write_text(schematic_to_kicad_sch(schematic, resolver), encoding="utf-8")
        proc = subprocess.run(
            [
                cli,
                "sch",
                "export",
                "svg",
                "--output",
                str(out_dir),
                "--exclude-drawing-sheet",
                "--no-background-color",
                "--black-and-white",
                str(sch_path),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "available": True,
                "pages": [],
                "error": (proc.stderr or proc.stdout or f"kicad-cli exited {proc.returncode}").strip(),
                "returncode": proc.returncode,
            }

        pages: list[dict[str, Any]] = []
        raw_pages: list[str] = []
        for path in sorted(out_dir.glob("*.svg")):
            text = path.read_text(encoding="utf-8")
            raw_pages.append(text)
            item: dict[str, Any] = {"name": path.name, "bytes": len(text.encode("utf-8"))}
            if include_svg:
                item["svg"] = text
            pages.append(item)
        if not pages:
            return {
                "available": True,
                "pages": [],
                "error": "KiCad SVG export produced no pages",
                "returncode": proc.returncode,
            }
        return {
            "available": True,
            "pages": pages,
            "page_count": len(pages),
            "returncode": proc.returncode,
            "stderr": proc.stderr.strip(),
            "_raw_pages": raw_pages,
        }


def review_schematic_visual(
    schematic: Schematic,
    circuit: Circuit | None = None,
    resolver: SymbolResolver | None = None,
    run_render: bool = True,
    include_svg: bool = False,
    provider: VisualReviewProvider | None = None,
) -> dict[str, Any]:
    """Score schematic readability without changing the design."""
    findings: list[VisualFinding] = []
    bounds = {item.reference: _symbol_bounds(schematic, item) for item in schematic.symbols}
    refs = sorted(bounds)
    overlap_count = 0
    near_count = 0
    for i, left in enumerate(refs):
        for right in refs[i + 1 :]:
            if _overlap(bounds[left], bounds[right]):
                overlap_count += 1
                findings.append(
                    VisualFinding(
                        "SYMBOL_OVERLAP",
                        "error",
                        f"{left} overlaps {right}",
                        25.0,
                        (left, right),
                    )
                )
            elif _box_gap(bounds[left], bounds[right]) < 5.08:
                near_count += 1
                findings.append(
                    VisualFinding(
                        "SYMBOL_SPACING",
                        "warning",
                        f"{left} is too close to {right}",
                        4.0,
                        (left, right),
                    )
                )

    crossings = _wire_crossings(schematic)
    findings.extend(
        VisualFinding(
            "WIRE_CROSSING",
            "warning",
            f"wire {left} crosses wire {right} without a junction",
            8.0,
        )
        for left, right in crossings
    )

    reversals = _flow_reversals(circuit, schematic)
    findings.extend(
        VisualFinding(
            "FLOW_REVERSAL",
            "warning",
            f"{net}: source {source} is to the right of sink {sink}",
            5.0,
            (source, sink),
        )
        for net, source, sink in reversals
    )

    lengths = [math.hypot(wire.x2 - wire.x1, wire.y2 - wire.y1) for wire in schematic.wires]
    total_wire = sum(lengths)
    max_wire = max(lengths, default=0.0)
    if max_wire > 120.0:
        findings.append(
            VisualFinding(
                "LONG_WIRE",
                "info",
                f"longest wire segment is {max_wire:.1f} mm",
                min(10.0, (max_wire - 120.0) / 20.0),
            )
        )

    if bounds:
        min_x = min(box[0] for box in bounds.values())
        min_y = min(box[1] for box in bounds.values())
        max_x = max(box[2] for box in bounds.values())
        max_y = max(box[3] for box in bounds.values())
        width, height = max_x - min_x, max_y - min_y
    else:
        width = height = 0.0
    aspect = width / height if height > 0 else 0.0
    if aspect > 6.0:
        findings.append(
            VisualFinding(
                "EXTREME_ASPECT_RATIO",
                "info",
                f"schematic layout is very wide ({aspect:.1f}:1)",
                4.0,
            )
        )

    render = (
        render_schematic_svg(schematic, resolver, include_svg=include_svg)
        if run_render
        else {"available": False, "pages": [], "error": "disabled"}
    )
    raw_pages = list(render.pop("_raw_pages", []))
    if render.get("available") and render.get("error"):
        findings.append(
            VisualFinding("SVG_RENDER_FAILED", "error", str(render["error"]), 25.0)
        )

    if provider is not None and raw_pages:
        findings.extend(
            provider.review(
                raw_pages,
                {
                    "symbols": len(schematic.symbols),
                    "wires": len(schematic.wires),
                    "labels": len(schematic.labels),
                    "width_mm": round(width, 2),
                    "height_mm": round(height, 2),
                },
            )
        )

    score = max(0.0, 100.0 - sum(item.penalty for item in findings))
    grade = (
        "A"
        if score >= 90
        else "B"
        if score >= 80
        else "C"
        if score >= 70
        else "D"
        if score >= 60
        else "F"
    )
    blocking = score < _BLOCKING_SCORE or any(
        item.code == "SVG_RENDER_FAILED" and item.severity == "error" for item in findings
    )
    return {
        "score": round(score, 1),
        "grade": grade,
        "acceptable": score >= _DEFAULT_TARGET_SCORE,
        "blocking": blocking,
        "findings": [item.as_dict() for item in findings],
        "metrics": {
            "symbols": len(schematic.symbols),
            "wires": len(schematic.wires),
            "labels": len(schematic.labels),
            "symbol_overlaps": overlap_count,
            "near_symbol_pairs": near_count,
            "wire_crossings": len(crossings),
            "flow_reversals": len(reversals),
            "wire_length_mm": round(total_wire, 2),
            "max_wire_segment_mm": round(max_wire, 2),
            "layout_width_mm": round(width, 2),
            "layout_height_mm": round(height, 2),
            "aspect_ratio": round(aspect, 2),
        },
        "render": render,
    }


def _pin_anchor(schematic: Schematic, reference: str, pin_number: str) -> tuple[float, float] | None:
    symbol = next((item for item in schematic.symbols if item.reference == reference), None)
    if symbol is None:
        return None
    library = schematic.library_symbols.get(symbol.lib_id)
    if library is None:
        return None
    pin = symbol_pin_geometry(library, symbol.unit).get(pin_number)
    if pin is None:
        return None
    dx, dy = _rotate(pin.x, pin.y, symbol.rotation)
    return _snap(symbol.x + dx), _snap(symbol.y + dy)


def _append_wire(
    target: list[Wire],
    seen: set[tuple[tuple[float, float], tuple[float, float]]],
    a: tuple[float, float],
    b: tuple[float, float],
) -> None:
    a, b = (_snap(a[0]), _snap(a[1])), (_snap(b[0]), _snap(b[1]))
    if a == b:
        return
    ordered = sorted((a, b))
    key = (ordered[0], ordered[1])
    if key in seen:
        return
    seen.add(key)
    target.append(Wire(x1=a[0], y1=a[1], x2=b[0], y2=b[1]))


def _route_net(
    name: str, endpoints: list[tuple[float, float]]
) -> tuple[list[Wire], NetLabel, list[Junction]]:
    points = sorted(set((_snap(x), _snap(y)) for x, y in endpoints))
    if not points:
        raise ValueError(f"net '{name}' has no drawable endpoints")
    if len(points) == 1:
        x, y = points[0]
        return [], NetLabel(text=name, x=x, y=y), []

    xs = sorted(x for x, _ in points)
    trunk_x = _snap(xs[len(xs) // 2])
    wires: list[Wire] = []
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for x, y in points:
        _append_wire(wires, seen, (x, y), (trunk_x, y))
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    _append_wire(wires, seen, (trunk_x, min_y), (trunk_x, max_y))

    junctions: list[Junction] = []
    if len(points) > 2:
        for y in sorted({y for _, y in points}):
            branches = sum(1 for x, py in points if py == y and x != trunk_x)
            if branches + int(min_y < y < max_y) >= 2:
                junctions.append(Junction(x=trunk_x, y=y))
    return wires, NetLabel(text=name, x=trunk_x, y=min_y), junctions


def _reroute(circuit: Circuit, schematic: Schematic) -> list[str]:
    unresolved: list[str] = []
    schematic.wires = []
    schematic.labels = []
    schematic.junctions = []
    for net_name in sorted(circuit.nets):
        endpoints: list[tuple[float, float]] = []
        for node in circuit.nets[net_name].nodes:
            anchor = _pin_anchor(schematic, node.component, node.pin)
            if anchor is None:
                unresolved.append(f"{net_name}: cannot locate {node.key()}")
            else:
                endpoints.append(anchor)
        if endpoints:
            wires, label, junctions = _route_net(net_name, endpoints)
            schematic.wires.extend(wires)
            schematic.labels.append(label)
            schematic.junctions.extend(junctions)
    unique = {(_snap(item.x), _snap(item.y)): item for item in schematic.junctions}
    schematic.junctions = list(unique.values())
    return unresolved


def _scale_layout(schematic: Schematic, scale_x: float, scale_y: float) -> None:
    if not schematic.symbols:
        return
    origin_x = min(symbol.x for symbol in schematic.symbols)
    origin_y = min(symbol.y for symbol in schematic.symbols)
    for symbol in schematic.symbols:
        symbol.x = _snap(origin_x + (symbol.x - origin_x) * scale_x)
        symbol.y = _snap(origin_y + (symbol.y - origin_y) * scale_y)


def optimize_visual_layout(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    target_score: float = _DEFAULT_TARGET_SCORE,
    max_passes: int = 4,
    run_render: bool = True,
    include_svg: bool = False,
) -> dict[str, Any]:
    """Try bounded geometry-only variants and keep the highest-scoring one."""
    if max_passes < 1:
        raise ValueError("max_passes must be >= 1")
    target_score = max(0.0, min(100.0, target_score))
    variants = [(1.0, 1.0), (1.2, 1.2), (1.4, 1.3), (0.9, 1.0)][:max_passes]
    baseline = schematic.model_copy(deep=True)
    attempts: list[dict[str, Any]] = []
    best: tuple[float, float, float, Schematic] | None = None

    for scale_x, scale_y in variants:
        candidate = baseline.model_copy(deep=True)
        _scale_layout(candidate, scale_x, scale_y)
        unresolved = _reroute(circuit, candidate)
        review = review_schematic_visual(candidate, circuit=circuit, resolver=resolver, run_render=False)
        score = 0.0 if unresolved else float(review["score"])
        attempts.append(
            {
                "scale_x": scale_x,
                "scale_y": scale_y,
                "score": score,
                "unresolved": unresolved,
            }
        )
        if best is None or score > best[0]:
            best = (score, scale_x, scale_y, candidate)
        if score >= target_score and not unresolved:
            break

    assert best is not None
    candidate_score, best_x, best_y, winner = best
    winner_by_ref = {symbol.reference: symbol for symbol in winner.symbols}
    for symbol in schematic.symbols:
        chosen = winner_by_ref[symbol.reference]
        symbol.x, symbol.y, symbol.rotation = chosen.x, chosen.y, chosen.rotation
    unresolved = _reroute(circuit, schematic)
    final_review = review_schematic_visual(
        schematic,
        circuit=circuit,
        resolver=resolver,
        run_render=run_render,
        include_svg=include_svg,
    )
    if unresolved:
        final_review["blocking"] = True
        final_review["acceptable"] = False

    return {
        "target_score": target_score,
        "target_met": float(final_review["score"]) >= target_score and not unresolved,
        "changed": not math.isclose(best_x, 1.0) or not math.isclose(best_y, 1.0),
        "selected_scale": {"x": best_x, "y": best_y},
        "candidate_score": candidate_score,
        "attempts": attempts,
        "unresolved": unresolved,
        "review": final_review,
        "blocking": bool(final_review["blocking"]),
    }


def evaluate_visual_schematic(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    target_score: float = _DEFAULT_TARGET_SCORE,
    max_passes: int = 4,
    run_external: bool = True,
    include_svg: bool = False,
) -> dict[str, Any]:
    """Full Phase-4 pipeline: compose -> visual optimize -> SVG -> ERC."""
    semantic = evaluate_schematic(circuit, schematic, resolver=resolver, run_external=False)
    if semantic["blocking"]:
        semantic["visual_review"] = {
            "target_score": target_score,
            "target_met": False,
            "changed": False,
            "attempts": [],
            "blocking": True,
            "review": review_schematic_visual(
                schematic,
                circuit=circuit,
                resolver=resolver,
                run_render=False,
            ),
        }
        return semantic

    visual = optimize_visual_layout(
        circuit,
        schematic,
        resolver=resolver,
        target_score=target_score,
        max_passes=max_passes,
        run_render=run_external,
        include_svg=include_svg,
    )
    external = (
        run_kicad_erc(schematic, resolver=resolver)
        if run_external
        else {"available": False, "blocking": False, "violations": [], "error": "disabled"}
    )
    semantic["kicad"] = external
    semantic["visual_review"] = visual
    semantic["blocking"] = bool(
        semantic["blocking"] or visual["blocking"] or external.get("blocking")
    )
    return semantic

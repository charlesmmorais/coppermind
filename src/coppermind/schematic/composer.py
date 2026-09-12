"""Deterministic Circuit IR -> drawable KiCad schematic composition.

The LLM owns electrical intent.  This module owns geometry: placement, pin
anchors, orthogonal wires, labels and junctions.  It deliberately consumes only
Circuit IR + resolved KiCad symbol definitions, so coordinates never need to be
part of the agent prompt.
"""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass
from typing import Any

from coppermind.circuit import Circuit, ElectricalType
from coppermind.schematic.models import Junction, NetLabel, Schematic, SchLibrarySymbol, Wire

_TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()]+')
_UNIT_SUFFIX_RE = re.compile(r"_(\d+)_(\d+)$")
_GRID = 2.54


@dataclass(frozen=True)
class PinGeometry:
    number: str
    unit: int
    x: float
    y: float
    rotation: float
    length: float


@dataclass(frozen=True)
class ComposeReport:
    components: int
    nets: int
    wires: int
    labels: int
    junctions: int
    unresolved_pins: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unresolved_pins

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "components": self.components,
            "nets": self.nets,
            "wires": self.wires,
            "labels": self.labels,
            "junctions": self.junctions,
            "unresolved_pins": list(self.unresolved_pins),
        }


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] == '"':
        return token[1:-1].replace(r'\"', '"').replace("\\\\", "\\")
    return token


def _parse_sexpr(text: str) -> list[Any]:
    stack: list[list[Any]] = []
    root: list[Any] | None = None
    for token in _TOKEN_RE.findall(text):
        if token == "(":
            node: list[Any] = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            if root is None:
                root = node
        elif token == ")":
            if not stack:
                raise ValueError("unbalanced KiCad S-expression")
            stack.pop()
        else:
            if not stack:
                raise ValueError("token outside KiCad S-expression")
            stack[-1].append(_unquote(token))
    if stack or root is None:
        raise ValueError("unbalanced KiCad S-expression")
    return root


def _child(node: list[Any], key: str) -> list[Any] | None:
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == key:
            return item
    return None


def _collect_pin_geometry(node: list[Any], unit: int = 1) -> list[PinGeometry]:
    found: list[PinGeometry] = []
    if node and node[0] == "symbol" and len(node) > 1 and isinstance(node[1], str):
        match = _UNIT_SUFFIX_RE.search(node[1])
        if match:
            unit = int(match.group(1))
    if node and node[0] == "pin":
        at = _child(node, "at")
        length = _child(node, "length")
        number = _child(node, "number")
        if at and number and len(at) >= 3 and len(number) > 1:
            found.append(
                PinGeometry(
                    number=str(number[1]),
                    unit=unit,
                    x=float(at[1]),
                    y=float(at[2]),
                    rotation=float(at[3]) if len(at) > 3 else 0.0,
                    length=float(length[1]) if length and len(length) > 1 else 0.0,
                )
            )
    for item in node:
        if isinstance(item, list):
            found.extend(_collect_pin_geometry(item, unit))
    return found


def symbol_pin_geometry(library: SchLibrarySymbol, unit: int) -> dict[str, PinGeometry]:
    """Return electrical connection anchors for one real KiCad symbol unit.

    KiCad unit 0 contains geometry/pins shared by every displayed unit.  When a
    unit-specific pin uses the same number it takes precedence over the common
    definition.
    """
    by_number: dict[str, PinGeometry] = {}
    for definition in library.definitions:
        root = _parse_sexpr(definition.raw_s_expression)
        for pin in _collect_pin_geometry(root):
            if pin.unit not in (0, unit):
                continue
            current = by_number.get(pin.number)
            if current is None or (current.unit == 0 and pin.unit == unit):
                by_number[pin.number] = pin
    return by_number


def _snap(value: float) -> float:
    return round(value / _GRID) * _GRID


def _coord(value: float) -> float:
    """Normalize float noise without moving an electrical connection point."""
    return round(value, 6)


def _component_graph(circuit: Circuit) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {ref: set() for ref in circuit.components}
    for net in circuit.nets.values():
        refs = sorted({node.component for node in net.nodes if node.component in graph})
        for i, left in enumerate(refs):
            for right in refs[i + 1 :]:
                graph[left].add(right)
                graph[right].add(left)
    return graph


def _source_score(circuit: Circuit, reference: str) -> tuple[int, int, str]:
    comp = circuit.components[reference]
    output_types = {ElectricalType.OUTPUT, ElectricalType.POWER_OUTPUT, ElectricalType.OPEN_COLLECTOR}
    input_types = {ElectricalType.INPUT, ElectricalType.POWER_INPUT}
    outputs = sum(pin.electrical_type in output_types for pin in comp.pins.values())
    inputs = sum(pin.electrical_type in input_types for pin in comp.pins.values())
    return outputs - inputs, len(comp.pins), reference


def _layout(circuit: Circuit, schematic: Schematic) -> None:
    """Connectivity-aware deterministic placement on a 2.54 mm grid."""
    graph = _component_graph(circuit)
    symbols = {sym.reference: sym for sym in schematic.symbols}
    unseen = set(graph)
    group = 0
    while unseen:
        component_refs: list[str] = []
        seed = min(unseen)
        q = deque([seed])
        unseen.remove(seed)
        while q:
            ref = q.popleft()
            component_refs.append(ref)
            for nxt in sorted(graph[ref]):
                if nxt in unseen:
                    unseen.remove(nxt)
                    q.append(nxt)

        root = max(component_refs, key=lambda ref: _source_score(circuit, ref))
        levels = {root: 0}
        q = deque([root])
        while q:
            ref = q.popleft()
            for nxt in sorted(graph[ref]):
                if nxt in component_refs and nxt not in levels:
                    levels[nxt] = levels[ref] + 1
                    q.append(nxt)
        for ref in component_refs:
            levels.setdefault(ref, 0)

        rows_by_level: dict[int, list[str]] = {}
        for ref in component_refs:
            rows_by_level.setdefault(levels[ref], []).append(ref)
        y_base = 25.4 + group * 76.2
        for level in sorted(rows_by_level):
            refs = sorted(rows_by_level[level])
            for row, ref in enumerate(refs):
                sym = symbols.get(ref)
                if sym is None:
                    continue
                sym.x = _snap(25.4 + level * 50.8)
                sym.y = _snap(y_base + row * 25.4)
                sym.rotation = 0.0
        group += 1


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)


def _pin_anchor(schematic: Schematic, reference: str, pin_number: str) -> tuple[float, float] | None:
    sym = next((item for item in schematic.symbols if item.reference == reference), None)
    if sym is None:
        return None
    library = schematic.library_symbols.get(sym.lib_id)
    if library is None:
        return None
    pin = symbol_pin_geometry(library, sym.unit).get(pin_number)
    if pin is None:
        return None

    # KiCad library symbol coordinates use Y-up while schematic sheet
    # coordinates use Y-down.  Preserve the exact pin endpoint: many real
    # symbols intentionally use half-grid offsets such as 1.27/3.81 mm.
    dx, dy = _rotate(pin.x, -pin.y, sym.rotation)
    return _coord(sym.x + dx), _coord(sym.y + dy)


def _segment_key(wire: Wire) -> tuple[tuple[float, float], tuple[float, float]]:
    a = (_coord(wire.x1), _coord(wire.y1))
    b = (_coord(wire.x2), _coord(wire.y2))
    return tuple(sorted((a, b)))  # type: ignore[return-value]


def _append_wire(target: list[Wire], seen: set, a: tuple[float, float], b: tuple[float, float]) -> None:
    a = (_coord(a[0]), _coord(a[1]))
    b = (_coord(b[0]), _coord(b[1]))
    if a == b:
        return
    wire = Wire(x1=a[0], y1=a[1], x2=b[0], y2=b[1])
    key = _segment_key(wire)
    if key not in seen:
        target.append(wire)
        seen.add(key)


def _route_net(name: str, endpoints: list[tuple[float, float]]) -> tuple[list[Wire], NetLabel, list[Junction]]:
    points = sorted(set((_coord(x), _coord(y)) for x, y in endpoints))
    if not points:
        raise ValueError(f"net '{name}' has no drawable endpoints")
    if len(points) == 1:
        x, y = points[0]
        return [], NetLabel(text=name, x=x, y=y), []

    xs = sorted(x for x, _ in points)
    trunk_x = _snap(xs[len(xs) // 2])
    wires: list[Wire] = []
    seen: set = set()
    for x, y in points:
        _append_wire(wires, seen, (x, y), (trunk_x, y))
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    _append_wire(wires, seen, (trunk_x, min_y), (trunk_x, max_y))

    junctions: list[Junction] = []
    if len(points) > 2:
        for y in sorted({y for _, y in points}):
            branches = sum(1 for x, py in points if py == y and not math.isclose(x, trunk_x))
            vertical = min_y < y < max_y
            if branches + int(vertical) >= 2:
                junctions.append(Junction(x=trunk_x, y=y))
    return wires, NetLabel(text=name, x=trunk_x, y=min_y), junctions


def compose_schematic(circuit: Circuit, schematic: Schematic) -> ComposeReport:
    """Lower semantic electrical intent into deterministic drawable geometry."""
    unresolved = list(circuit.validate_references())
    symbol_refs = {sym.reference for sym in schematic.symbols}
    for ref in circuit.components:
        if ref not in symbol_refs:
            unresolved.append(f"{ref}: no drawable symbol instance")

    _layout(circuit, schematic)
    schematic.wires = []
    schematic.labels = []
    schematic.junctions = []

    for net_name in sorted(circuit.nets):
        net = circuit.nets[net_name]
        endpoints: list[tuple[float, float]] = []
        for node in net.nodes:
            anchor = _pin_anchor(schematic, node.component, node.pin)
            if anchor is None:
                unresolved.append(f"{net_name}: cannot locate {node.key()} in resolved symbol geometry")
            else:
                endpoints.append(anchor)
        if not endpoints:
            continue
        wires, label, junctions = _route_net(net_name, endpoints)
        schematic.wires.extend(wires)
        schematic.labels.append(label)
        schematic.junctions.extend(junctions)

    unique_junctions: dict[tuple[float, float], Junction] = {}
    for junction in schematic.junctions:
        unique_junctions.setdefault((_coord(junction.x), _coord(junction.y)), junction)
    schematic.junctions = list(unique_junctions.values())

    return ComposeReport(
        components=len(schematic.symbols),
        nets=len(circuit.nets),
        wires=len(schematic.wires),
        labels=len(schematic.labels),
        junctions=len(schematic.junctions),
        unresolved_pins=tuple(sorted(set(unresolved))),
    )

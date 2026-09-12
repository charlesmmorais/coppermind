"""Deterministic Circuit IR -> drawable KiCad schematic composition.

The LLM owns electrical intent. This module owns geometry: placement, pin
anchors, orthogonal wires, labels and junctions. It deliberately consumes only
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
_HORIZONTAL_LEVEL_GAP = 50.8
_VERTICAL_ROW_GAP = 50.8
_POWER_CHAIN_GAP = 25.4
_POWER_FLAG_OFFSET = 15.24
_POWER_SYMBOL_OFFSET = 15.24


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

    KiCad unit 0 contains geometry/pins shared by every displayed unit. When a
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


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)


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


def _is_power_marker(circuit: Circuit, reference: str) -> bool:
    component = circuit.components.get(reference)
    return component is not None and component.symbol_id.lower().startswith("power:")


def _is_power_flag(circuit: Circuit, reference: str) -> bool:
    component = circuit.components.get(reference)
    return component is not None and component.symbol_id.lower() == "power:pwr_flag"


def _is_ground_marker(circuit: Circuit, reference: str) -> bool:
    component = circuit.components.get(reference)
    if component is None:
        return False
    token = f"{component.symbol_id}:{component.value}".lower()
    return "gnd" in token or "vss" in token


def _groups(graph: dict[str, set[str]]) -> list[list[str]]:
    unseen = set(graph)
    result: list[list[str]] = []
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        q = deque([seed])
        refs: list[str] = []
        while q:
            ref = q.popleft()
            refs.append(ref)
            for nxt in sorted(graph[ref]):
                if nxt in unseen:
                    unseen.remove(nxt)
                    q.append(nxt)
        result.append(sorted(refs))
    return result


def _primary_graph(graph: dict[str, set[str]], refs: list[str], primary: set[str]) -> dict[str, set[str]]:
    return {
        ref: {nxt for nxt in graph[ref] if nxt in primary}
        for ref in refs
        if ref in primary
    }


def _refs_on_power_nets(circuit: Circuit, refs: set[str], *, ground: bool) -> set[str]:
    found: set[str] = set()
    for net in circuit.nets.values():
        net_refs = {node.component for node in net.nodes}
        markers = [ref for ref in net_refs if ref in refs and _is_power_marker(circuit, ref)]
        if not markers:
            continue
        if ground:
            active = any(_is_ground_marker(circuit, ref) for ref in markers)
        else:
            active = any(
                not _is_ground_marker(circuit, ref) and not _is_power_flag(circuit, ref)
                for ref in markers
            )
        if active:
            found.update(ref for ref in net_refs if ref in refs and not _is_power_marker(circuit, ref))
    return found


def _path_covering_graph(
    graph: dict[str, set[str]],
    starts: set[str],
    ends: set[str],
) -> list[str] | None:
    if not graph or not starts or not ends:
        return None
    for start in sorted(starts):
        q = deque([start])
        parent: dict[str, str | None] = {start: None}
        target: str | None = None
        while q:
            ref = q.popleft()
            if ref in ends:
                target = ref
                break
            for nxt in sorted(graph.get(ref, ())):
                if nxt not in parent:
                    parent[nxt] = ref
                    q.append(nxt)
        if target is None:
            continue
        path: list[str] = []
        current: str | None = target
        while current is not None:
            path.append(current)
            current = parent[current]
        path.reverse()
        if set(path) == set(graph):
            return path
    return None


def _symbol_by_ref(schematic: Schematic, reference: str):
    return next((item for item in schematic.symbols if item.reference == reference), None)


def _place_symbol_pin_at(
    schematic: Schematic,
    reference: str,
    pin_number: str,
    target: tuple[float, float],
) -> bool:
    symbol = _symbol_by_ref(schematic, reference)
    if symbol is None:
        return False
    library = schematic.library_symbols.get(symbol.lib_id)
    if library is None:
        return False
    pin = symbol_pin_geometry(library, symbol.unit).get(pin_number)
    if pin is None:
        return False
    symbol.rotation = 0.0
    dx, dy = _rotate(pin.x, -pin.y, symbol.rotation)
    symbol.x = _coord(target[0] - dx)    symbol.y = _coord(target[1] - dy)
    return True


def _connected_pin(circuit: Circuit, net_name: str, reference: str) -> str | None:
    net = circuit.nets.get(net_name)
    if net is None:
        return None
    for node in net.nodes:
        if node.component == reference:
            return node.pin
    return None


def _place_power_markers(
    circuit: Circuit,
    schematic: Schematic,
    group_refs: set[str],
    primary: set[str],
) -> None:
    """Place power rail annotations around the functional endpoint.

    Named rail glyphs sit above/below the attached functional pin with a short
    wire; PWR_FLAGs sit beside the rail. This keeps semantic connectivity while
    avoiding deliberate symbol overlap in the visual reviewer.
    """
    for net_name in sorted(circuit.nets):
        net = circuit.nets[net_name]
        nodes = [node for node in net.nodes if node.component in group_refs]
        markers = sorted(
            {node.component for node in nodes if _is_power_marker(circuit, node.component)}
        )
        primary_nodes = [node for node in nodes if node.component in primary]
        if not markers or not primary_nodes:
            continue

        anchors = [
            anchor
            for node in primary_nodes
            if (anchor := _pin_anchor(schematic, node.component, node.pin)) is not None
        ]
        if not anchors:
            continue
        base = min(anchors, key=lambda point: (point[1], point[0]))

        ordinary = [ref for ref in markers if not _is_power_flag(circuit, ref)]
        flags = [ref for ref in markers if _is_power_flag(circuit, ref)]

        for index, ref in enumerate(ordinary):
            pin = _connected_pin(circuit, net_name, ref)
            if pin is None:
                continue
            vertical = _POWER_SYMBOL_OFFSET if _is_ground_marker(circuit, ref) else -_POWER_SYMBOL_OFFSET
            target = (
                _coord(base[0] + index * 15.24),
                _coord(base[1] + vertical),
            )
            _place_symbol_pin_at(schematic, ref, pin, target)

        for index, ref in enumerate(flags):
            pin = _connected_pin(circuit, net_name, ref)
            if pin is None:
                continue
            direction = -1.0 if index % 2 == 0 else 1.0
            rank = index // 2 + 1
            target = (
                _coord(base[0] + direction * _POWER_FLAG_OFFSET * rank),
                base[1],
            )
            _place_symbol_pin_at(schematic, ref, pin, target)


def _layout_power_chain(
    circuit: Circuit,
    schematic: Schematic,
    refs: list[str],
    graph: dict[str, set[str]],
    y_base: float,
) -> float | None:
    primary = {ref for ref in refs if not _is_power_marker(circuit, ref)}
    markers = {ref for ref in refs if _is_power_marker(circuit, ref)}
    if not primary or not markers:
        return None
    if any(len(circuit.components[ref].pins) > 2 for ref in primary):
        return None

    pgraph = _primary_graph(graph, refs, primary)
    if any(len(neighbors) > 2 for neighbors in pgraph.values()):
        return None

    top = _refs_on_power_nets(circuit, set(refs), ground=False)
    bottom = _refs_on_power_nets(circuit, set(refs), ground=True)
    order = _path_covering_graph(pgraph, top, bottom)
    if order is None:
        return None

    symbols = {symbol.reference: symbol for symbol in schematic.symbols}
    x = _snap(76.2)
    start_y = _snap(y_base + 12.7)
    for index, ref in enumerate(order):
        symbol = symbols.get(ref)
        if symbol is None:
            continue
        symbol.x = x
        symbol.y = _snap(start_y + index * _POWER_CHAIN_GAP)
        symbol.rotation = 0.0

    _place_power_markers(circuit, schematic, set(refs), primary)
    return max(76.2, len(order) * _POWER_CHAIN_GAP + 38.1)


def _layout_generic_group(
    circuit: Circuit,
    schematic: Schematic,
    refs: list[str],
    graph: dict[str, set[str]],
    y_base: float,
) -> float:
    symbols = {sym.reference: sym for sym in schematic.symbols}
    primary = {ref for ref in refs if not _is_power_marker(circuit, ref)}
    if not primary:
        primary = set(refs)

    pgraph = _primary_graph(graph, refs, primary)
    root = max(primary, key=lambda ref: _source_score(circuit, ref))
    levels = {root: 0}
    q = deque([root])
    while q:
        ref = q.popleft()
        for nxt in sorted(pgraph.get(ref, ())):
            if nxt not in levels:
                levels[nxt] = levels[ref] + 1
                q.append(nxt)
    for ref in primary:
        levels.setdefault(ref, 0)

    rows_by_level: dict[int, list[str]] = {}
    for ref in primary:
        rows_by_level.setdefault(levels[ref], []).append(ref)

    max_rows = 1
    for level in sorted(rows_by_level):
        level_refs = sorted(rows_by_level[level])
        max_rows = max(max_rows, len(level_refs))
        for row, ref in enumerate(level_refs):
            symbol = symbols.get(ref)
            if symbol is None:
                continue
            symbol.x = _snap(38.1 + level * _HORIZONTAL_LEVEL_GAP)
            symbol.y = _snap(y_base + row * _VERTICAL_ROW_GAP)            symbol.rotation = 0.0

    marker_refs = set(refs) - primary
    if marker_refs:
        _place_power_markers(circuit, schematic, set(refs), primary)

    return max(50.8, max_rows * _VERTICAL_ROW_GAP + 25.4)


def _layout(circuit: Circuit, schematic: Schematic) -> None:
    """Connectivity-aware deterministic placement.

    Functional signal blocks still flow left-to-right. A simple two-pin chain
    bounded by named power rails is instead laid out top-to-bottom, matching
    conventional schematic reading for dividers, pull-ups and bias chains.
    Power glyphs/PWR_FLAGs are rail annotations and are placed near their
    functional endpoint instead of becoming BFS stages of their own.
    """
    graph = _component_graph(circuit)
    y_cursor = 38.1
    for refs in _groups(graph):
        consumed = _layout_power_chain(circuit, schematic, refs, graph, y_cursor)
        if consumed is None:
            consumed = _layout_generic_group(circuit, schematic, refs, graph, y_cursor)
        y_cursor += consumed


def _pin_anchor(schematic: Schematic, reference: str, pin_number: str) -> tuple[float, float] | None:
    sym = _symbol_by_ref(schematic, reference)
    if sym is None:
        return None
    library = schematic.library_symbols.get(sym.lib_id)
    if library is None:
        return None
    pin = symbol_pin_geometry(library, sym.unit).get(pin_number)
    if pin is None:
        return None

    # KiCad library symbol coordinates use Y-up while schematic sheet
    # coordinates use Y-down. Preserve the exact pin endpoint: many real
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

    # A pin that lands on the middle of one long trunk segment is only a
    # geometric crossing to KiCad; it is not necessarily an electrical node.
    # Split the trunk at every endpoint Y so each collinear pin is a real wire
    # endpoint, then add a junction whenever three or more electrical legs meet.
    ys = sorted({y for _, y in points})
    for y0, y1 in zip(ys, ys[1:]):
        _append_wire(wires, seen, (trunk_x, y0), (trunk_x, y1))

    junctions: list[Junction] = []
    if len(points) > 2:
        min_y, max_y = ys[0], ys[-1]
        for y in ys:
            branches = sum(
                1 for x, py in points if py == y and not math.isclose(x, trunk_x)
            )
            on_trunk = sum(
                1 for x, py in points if py == y and math.isclose(x, trunk_x)
            )
            vertical_sides = int(y > min_y) + int(y < max_y)
            if branches + on_trunk + vertical_sides >= 3:
                junctions.append(Junction(x=trunk_x, y=y))

    # Keep labels on the electrical wire, but away from the first pin endpoint.
    # A midpoint/median placement is more readable for simple two-node nets.
    if len(points) == 2 and math.isclose(points[0][0], points[1][0]):
        label_x = points[0][0]
        label_y = _coord((points[0][1] + points[1][1]) / 2.0)
    elif len(points) == 2 and math.isclose(points[0][1], points[1][1]):
        label_x = _coord((points[0][0] + points[1][0]) / 2.0)
        label_y = points[0][1]
    else:
        label_x = trunk_x
        label_y = ys[len(ys) // 2]
    return wires, NetLabel(text=name, x=label_x, y=label_y), junctions


def _net_has_named_power_symbol(circuit: Circuit, net_name: str) -> bool:
    net = circuit.nets.get(net_name)
    if net is None:
        return False
    return any(
        _is_power_marker(circuit, node.component) and not _is_power_flag(circuit, node.component)
        for node in net.nodes
    )


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
        schematic.wires.extend(wires)        if not _net_has_named_power_symbol(circuit, net_name):
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
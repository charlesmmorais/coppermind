"""Pure writer: a Coppermind Schematic -> KiCad ``.kicad_sch`` text.

Library graphics and pins come from the user's real KiCad ``.kicad_sym`` files.
No generic two-pin fallback is generated.
"""

from __future__ import annotations

import math
import uuid as _uuid
from dataclasses import dataclass

from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import symbol_pin_geometry
from coppermind.schematic.models import (
    Schematic,
    SchLibraryDefinition,
    SchLibrarySymbol,
)

_VERSION = "20231120"  # KiCad 8 format; KiCad 9/10 open and upgrade it.
_FIELD_CLEARANCE = 5.08
_FIELD_STACK_OFFSET = 1.27
_POWER_VALUE_OFFSET = 3.81
_POWER_REFERENCE_OFFSET = 2.54
_TEXT_HEIGHT = 1.27
_TEXT_CHAR_WIDTH = 0.84
_LABEL_MARGIN = 0.635
_LABEL_CANDIDATE_FRACTIONS = (0.5, 1.0 / 3.0, 2.0 / 3.0, 0.25, 0.75)

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class _LabelPlacement:
    x: float
    y: float
    rotation: float
    justify: str


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())


def _fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _uid() -> str:
    return str(_uuid.uuid4())


def _as_schematic_library(resolved) -> SchLibrarySymbol:
    return SchLibrarySymbol(
        lib_id=resolved.lib_id,
        source_path=resolved.source_path,
        pins=resolved.pins,
        definitions=[
            SchLibraryDefinition(lib_id=d.lib_id, raw_s_expression=d.raw_s_expression)
            for d in resolved.definitions
        ],
    )


def _resolved_library_symbols(
    sch: Schematic,
    resolver: SymbolResolver | None,
) -> dict[str, SchLibrarySymbol]:
    result = dict(sch.library_symbols)
    missing = {sym.lib_id for sym in sch.symbols} - set(result)
    if missing:
        active = resolver or SymbolResolver()
        for lib_id in sorted(missing):
            result[lib_id] = _as_schematic_library(active.resolve(lib_id))
    return result


def _two_pin_orientation(sym, library: SchLibrarySymbol) -> str | None:
    """Infer the displayed axis of a two-pin symbol from its real pin geometry."""
    pins = list(symbol_pin_geometry(library, sym.unit).values())
    if len(pins) != 2:
        return None
    left, right = pins
    dx = abs(left.x - right.x)
    dy = abs(left.y - right.y)
    if abs(dx - dy) < 1e-6:
        return None
    vertical = dy > dx
    if int(round(sym.rotation / 90.0)) % 2:
        vertical = not vertical
    return "vertical" if vertical else "horizontal"


def _field_counter_rotation(sym) -> float:
    """Keep instance fields upright when KiCad rotates the parent symbol.

    Property angles are interpreted in the symbol-instance coordinate frame.
    A 90-degree symbol with a zero-degree property therefore renders the field
    vertically. Counter-rotating the property keeps Reference/Value readable
    in sheet coordinates while the component body follows electrical flow.
    """
    rotation = (-float(sym.rotation)) % 360.0
    if math.isclose(rotation, 360.0, abs_tol=1e-6) or math.isclose(
        rotation, 0.0, abs_tol=1e-6
    ):
        return 0.0
    return rotation


def _field_layout(
    sym,
    library: SchLibrarySymbol,
) -> dict[str, tuple[float, float, float, bool, str | None]]:
    """Place instance fields with deterministic body/wire clearance.

    Two-pin symbols are aligned according to their displayed axis: vertical
    parts get a compact left-justified field stack to the right, while
    horizontal parts get centered fields above/below the body. Other symbols
    use the safer top/bottom fallback. Power glyphs retain their conventional
    value side and hide their generated reference. Field text is counter-
    rotated against the parent symbol so Reference/Value stay upright.
    """
    token = sym.lib_id.lower()
    is_power = token.startswith("power:")
    hidden_reference = is_power or sym.reference.startswith("#")
    field_rotation = _field_counter_rotation(sym)

    if is_power:
        value_y = sym.y + _POWER_VALUE_OFFSET
        if not any(name in token for name in ("gnd", "vss", "pwr_flag")):
            value_y = sym.y - _POWER_VALUE_OFFSET
        return {
            "Reference": (
                sym.x,
                sym.y - _POWER_REFERENCE_OFFSET,
                field_rotation,
                hidden_reference,
                None,
            ),
            "Value": (sym.x, value_y, field_rotation, False, None),
        }

    orientation = _two_pin_orientation(sym, library)
    if orientation == "vertical":
        field_x = sym.x + _FIELD_CLEARANCE
        return {
            "Reference": (
                field_x,
                sym.y - _FIELD_STACK_OFFSET,
                field_rotation,
                hidden_reference,
                "left",
            ),
            "Value": (
                field_x,
                sym.y + _FIELD_STACK_OFFSET,
                field_rotation,
                False,
                "left",
            ),
        }

    if orientation == "horizontal":
        return {
            "Reference": (
                sym.x,
                sym.y - _FIELD_CLEARANCE,
                field_rotation,
                hidden_reference,
                None,
            ),
            "Value": (
                sym.x,
                sym.y + _FIELD_CLEARANCE,
                field_rotation,
                False,
                None,
            ),
        }

    return {
        "Reference": (
            sym.x,
            sym.y - _FIELD_CLEARANCE,
            field_rotation,
            hidden_reference,
            None,
        ),
        "Value": (
            sym.x,
            sym.y + _FIELD_CLEARANCE,
            field_rotation,
            False,
            None,
        ),
    }


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    return (
        x * math.cos(angle) - y * math.sin(angle),
        x * math.sin(angle) + y * math.cos(angle),
    )


def _text_box(text: str, x: float, y: float, justify: str | None = None) -> Box:
    """Approximate a KiCad text box closely enough for deterministic clearance."""
    width = max(_TEXT_HEIGHT, len(text) * _TEXT_CHAR_WIDTH)
    height = _TEXT_HEIGHT
    tokens = set((justify or "").split())

    if "left" in tokens:
        x0, x1 = x, x + width
    elif "right" in tokens:
        x0, x1 = x - width, x
    else:
        x0, x1 = x - width / 2.0, x + width / 2.0

    if "top" in tokens:
        y0, y1 = y, y + height
    elif "bottom" in tokens:
        y0, y1 = y - height, y
    else:
        y0, y1 = y - height / 2.0, y + height / 2.0

    return (
        x0 - _LABEL_MARGIN,
        y0 - _LABEL_MARGIN,
        x1 + _LABEL_MARGIN,
        y1 + _LABEL_MARGIN,
    )


def _boxes_overlap(left: Box, right: Box) -> bool:
    return not (
        left[2] <= right[0]
        or right[2] <= left[0]
        or left[3] <= right[1]
        or right[3] <= left[1]
    )


def _symbol_body_box(sym, library: SchLibrarySymbol) -> Box:
    points: list[tuple[float, float]] = []
    for pin in symbol_pin_geometry(library, sym.unit).values():
        dx, dy = _rotate(pin.x, -pin.y, sym.rotation)
        points.append((sym.x + dx, sym.y + dy))
    if not points:
        points = [(sym.x - 2.54, sym.y - 2.54), (sym.x + 2.54, sym.y + 2.54)]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    margin = 1.27
    return (
        min(xs) - margin,
        min(ys) - margin,
        max(xs) + margin,
        max(ys) + margin,
    )


def _field_boxes(
    sch: Schematic,
    libraries: dict[str, SchLibrarySymbol],
) -> list[Box]:
    boxes: list[Box] = []
    for sym in sch.symbols:
        library = libraries[sym.lib_id]
        fields = _field_layout(sym, library)
        values = {"Reference": sym.reference, "Value": sym.value}
        for name, value in values.items():
            x, y, _rotation, hidden, justify = fields[name]
            if hidden or not value:
                continue
            boxes.append(_text_box(value, x, y, justify))
    return boxes


def _point_on_wire(x: float, y: float, wire, eps: float = 1e-6) -> bool:
    if math.isclose(wire.y1, wire.y2, abs_tol=eps):
        return (
            math.isclose(y, wire.y1, abs_tol=eps)
            and min(wire.x1, wire.x2) - eps <= x <= max(wire.x1, wire.x2) + eps
        )
    if math.isclose(wire.x1, wire.x2, abs_tol=eps):
        return (
            math.isclose(x, wire.x1, abs_tol=eps)
            and min(wire.y1, wire.y2) - eps <= y <= max(wire.y1, wire.y2) + eps
        )
    return False


def _wires_connected(left, right) -> bool:
    left_points = ((left.x1, left.y1), (left.x2, left.y2))
    right_points = ((right.x1, right.y1), (right.x2, right.y2))
    return any(_point_on_wire(x, y, right) for x, y in left_points) or any(
        _point_on_wire(x, y, left) for x, y in right_points
    )


def _label_network(sch: Schematic, label) -> set[int]:
    """Return the connected wire component carrying a label's current anchor."""
    seeds = {
        index
        for index, wire in enumerate(sch.wires)
        if _point_on_wire(label.x, label.y, wire)
    }
    if not seeds:
        return set()

    network = set(seeds)
    frontier = list(seeds)
    while frontier:
        index = frontier.pop()
        current = sch.wires[index]
        for other_index, other in enumerate(sch.wires):
            if other_index in network:
                continue
            if _wires_connected(current, other):
                network.add(other_index)
                frontier.append(other_index)
    return network


def _wire_intersects_box(wire, box: Box) -> bool:
    if math.isclose(wire.y1, wire.y2):
        x0, x1 = sorted((wire.x1, wire.x2))
        return box[1] < wire.y1 < box[3] and x1 > box[0] and x0 < box[2]
    if math.isclose(wire.x1, wire.x2):
        y0, y1 = sorted((wire.y1, wire.y2))
        return box[0] < wire.x1 < box[2] and y1 > box[1] and y0 < box[3]
    return False


def _point_in_box(x: float, y: float, box: Box) -> bool:
    return box[0] < x < box[2] and box[1] < y < box[3]


def _candidate_points(wire) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for fraction in _LABEL_CANDIDATE_FRACTIONS:
        points.append(
            (
                wire.x1 + (wire.x2 - wire.x1) * fraction,
                wire.y1 + (wire.y2 - wire.y1) * fraction,
            )
        )
    return points


def _label_score(
    sch: Schematic,
    label,
    placement: _LabelPlacement,
    network: set[int],
    field_boxes: list[Box],
    body_boxes: list[Box],
    occupied: list[Box],
) -> tuple[float, float, float, str]:
    box = _text_box(label.text, placement.x, placement.y, placement.justify)
    penalty = 0.0
    penalty += 120.0 * sum(_boxes_overlap(box, item) for item in occupied)
    penalty += 100.0 * sum(_boxes_overlap(box, item) for item in field_boxes)
    penalty += 80.0 * sum(_boxes_overlap(box, item) for item in body_boxes)

    for index, wire in enumerate(sch.wires):
        if index not in network and _wire_intersects_box(wire, box):
            penalty += 50.0

    for junction in sch.junctions:
        if _point_in_box(junction.x, junction.y, box) and not (
            math.isclose(junction.x, placement.x)
            and math.isclose(junction.y, placement.y)
        ):
            penalty += 30.0

    distance = math.hypot(placement.x - label.x, placement.y - label.y)
    return penalty, distance, placement.x + placement.y, placement.justify


def _label_layouts(
    sch: Schematic,
    libraries: dict[str, SchLibrarySymbol],
) -> dict[str, _LabelPlacement]:
    """Place labels on their own wires while avoiding fields and nearby geometry."""
    field_boxes = _field_boxes(sch, libraries)
    body_boxes = [
        _symbol_body_box(sym, libraries[sym.lib_id])
        for sym in sch.symbols
    ]
    occupied: list[Box] = []
    result: dict[str, _LabelPlacement] = {}

    for label in sch.labels:
        network = _label_network(sch, label)
        if not network:
            placement = _LabelPlacement(
                label.x,
                label.y,
                label.rotation,
                "left bottom",
            )
            result[label.uuid] = placement
            occupied.append(_text_box(label.text, placement.x, placement.y, placement.justify))
            continue

        candidates: list[_LabelPlacement] = []
        for justify in ("left bottom", "right bottom", "left top", "right top"):
            candidates.append(_LabelPlacement(label.x, label.y, label.rotation, justify))

        for index in sorted(network):
            wire = sch.wires[index]
            for x, y in _candidate_points(wire):
                for justify in ("left bottom", "right bottom", "left top", "right top"):
                    candidate = _LabelPlacement(x, y, label.rotation, justify)
                    if candidate not in candidates:
                        candidates.append(candidate)

        placement = min(
            candidates,
            key=lambda item: _label_score(
                sch,
                label,
                item,
                network,
                field_boxes,
                body_boxes,
                occupied,
            ),
        )
        result[label.uuid] = placement
        occupied.append(_text_box(label.text, placement.x, placement.y, placement.justify))

    return result


def _property(
    name: str,
    value: str,
    x: float,
    y: float,
    rotation: float,
    *,
    hidden: bool = False,
    justify: str | None = None,
) -> str:
    hidden_text = " (hide yes)" if hidden else ""
    justify_text = f" (justify {justify})" if justify else ""
    return (
        f'  (property "{name}" "{value}" (at {_fmt(x)} {_fmt(y)} {_fmt(rotation)})'
        f"{hidden_text} (effects (font (size 1.27 1.27)){justify_text}))"
    )


def _symbol_instance(sym, project: str, library: SchLibrarySymbol) -> str:
    x, y, rot = _fmt(sym.x), _fmt(sym.y), _fmt(sym.rotation)
    fields = _field_layout(sym, library)
    lines: list[str] = []
    lines.append("(symbol")
    lines.append(f'  (lib_id "{sym.lib_id}")')
    lines.append(f"  (at {x} {y} {rot})")
    lines.append(f"  (unit {sym.unit})")
    lines.append("  (exclude_from_sim no)")
    lines.append("  (in_bom yes)")
    lines.append("  (on_board yes)")
    lines.append("  (dnp no)")
    lines.append(f'  (uuid "{sym.uuid}")')
    ref_x, ref_y, ref_rot, ref_hidden, ref_justify = fields["Reference"]
    lines.append(
        _property(
            "Reference",
            sym.reference,
            ref_x,
            ref_y,
            ref_rot,
            hidden=ref_hidden,
            justify=ref_justify,
        )
    )
    value_x, value_y, value_rot, value_hidden, value_justify = fields["Value"]
    lines.append(
        _property(
            "Value",
            sym.value,
            value_x,
            value_y,
            value_rot,
            hidden=value_hidden,
            justify=value_justify,
        )
    )
    seen: set[str] = set()
    for pin in library.pins_for_unit(sym.unit):
        if pin.number in seen:
            continue
        seen.add(pin.number)
        lines.append(f'  (pin "{pin.number}" (uuid "{_uid()}"))')
    lines.append("  (instances")
    lines.append(f'    (project "{project}"')
    lines.append(f'      (path "/{sym.uuid}" (reference "{sym.reference}") (unit {sym.unit}))')
    lines.append("    )")
    lines.append("  )")
    lines.append(")")
    return "\n".join(lines)


def _wire(w) -> str:
    return (
        "(wire (pts "
        f"(xy {_fmt(w.x1)} {_fmt(w.y1)}) (xy {_fmt(w.x2)} {_fmt(w.y2)}))\n"
        "  (stroke (width 0) (type default))\n"
        f'  (uuid "{w.uuid}")\n'
        ")"
    )


def _junction(j) -> str:
    return (
        f"(junction (at {_fmt(j.x)} {_fmt(j.y)}) (diameter 0) (color 0 0 0 0)\n"
        f'  (uuid "{j.uuid}")\n'
        ")"
    )


def _label(label, placement: _LabelPlacement) -> str:
    return (
        f'(label "{label.text}" '
        f"(at {_fmt(placement.x)} {_fmt(placement.y)} {_fmt(placement.rotation)})\n"
        f"  (effects (font (size 1.27 1.27)) (justify {placement.justify}))\n"
        f'  (uuid "{label.uuid}")\n'
        ")"
    )


def schematic_to_kicad_sch(
    sch: Schematic,
    resolver: SymbolResolver | None = None,
) -> str:
    libraries = _resolved_library_symbols(sch, resolver)
    label_layouts = _label_layouts(sch, libraries)
    out: list[str] = []
    out.append("(kicad_sch")
    out.append(f"  (version {_VERSION})")
    out.append('  (generator "coppermind")')
    out.append('  (generator_version "0.2")')
    out.append(f'  (uuid "{sch.uuid}")')
    out.append(f'  (paper "{sch.paper}")')

    definitions: dict[str, str] = {}
    for lib_id in sorted({s.lib_id for s in sch.symbols}):
        for definition in libraries[lib_id].definitions:
            definitions.setdefault(definition.lib_id, definition.raw_s_expression)
    out.append("  (lib_symbols")
    for raw in definitions.values():
        out.append(_indent(raw, 4))
    out.append("  )")

    for w in sch.wires:
        out.append(_indent(_wire(w), 2))
    for j in sch.junctions:
        out.append(_indent(_junction(j), 2))
    for label in sch.labels:
        out.append(_indent(_label(label, label_layouts[label.uuid]), 2))
    for sym in sch.symbols:
        out.append(_indent(_symbol_instance(sym, sch.name, libraries[sym.lib_id]), 2))

    out.append("  (sheet_instances")
    out.append('    (path "/" (page "1"))')
    out.append("  )")
    out.append(")")
    return "\n".join(out) + "\n"

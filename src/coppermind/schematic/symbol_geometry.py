"""Bounds of real library graphics, excluding pins and instance text."""

from __future__ import annotations

from functools import lru_cache
import math
import re

from coppermind.schematic.composer import _child, _parse_sexpr, symbol_sheet_offset
from coppermind.schematic.models import SchLibrarySymbol, SchSymbol, Wire

Box = tuple[float, float, float, float]


@lru_cache(maxsize=512)
def _graphic_points(raw: str, unit: int) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []

    def visit(node: list, active: int = 0) -> None:
        if not node:
            return
        if node[0] == "symbol":
            match = re.search(r"_(\d+)_(\d+)$", str(node[1]))
            if match:
                active = int(match[1])
                if active not in (0, unit) or int(match[2]) not in (0, 1):
                    return
            for child in node[2:]:
                if isinstance(child, list):
                    visit(child, active)
        elif node[0] in ("rectangle", "polyline", "bezier"):
            pts = _child(node, "pts")
            for item in pts[1:] if pts else [_child(node, "start"), _child(node, "end")]:
                if item and len(item) >= 3:
                    points.append((float(item[1]), float(item[2])))
        elif node[0] == "circle":
            center, radius = _child(node, "center"), _child(node, "radius")
            if center and radius:
                x, y, r = float(center[1]), float(center[2]), float(radius[1])
                points.extend(((x - r, y - r), (x + r, y + r)))
        elif node[0] == "arc":
            # A conservative circle envelope also covers extrema between the
            # three arc points, including arcs larger than a semicircle.
            pts = [_child(node, key) for key in ("start", "mid", "end")]
            if all(pts):
                a, b, c = [(float(p[1]), float(p[2])) for p in pts if p]
                d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
                if abs(d) < 1e-9:
                    points.extend((a, b, c))
                else:
                    aa, bb, cc = [x * x + y * y for x, y in (a, b, c)]
                    x = (aa * (b[1] - c[1]) + bb * (c[1] - a[1]) + cc * (a[1] - b[1])) / d
                    y = (aa * (c[0] - b[0]) + bb * (a[0] - c[0]) + cc * (b[0] - a[0])) / d
                    r = math.hypot(x - a[0], y - a[1])
                    points.extend(((x - r, y - r), (x + r, y + r)))

    visit(_parse_sexpr(raw))
    return tuple(points)


def symbol_graphic_box(symbol: SchSymbol, library: SchLibrarySymbol) -> Box | None:
    local = [
        point
        for definition in library.definitions
        for point in _graphic_points(definition.raw_s_expression, symbol.unit)
    ]
    if not local:
        return None
    xs, ys = [p[0] for p in local], [p[1] for p in local]
    points = [
        symbol_sheet_offset(x, y, symbol.rotation)
        for x in (min(xs), max(xs))
        for y in (min(ys), max(ys))
    ]
    return (
        symbol.x + min(x for x, y in points),
        symbol.y + min(y for x, y in points),
        symbol.x + max(x for x, y in points),
        symbol.y + max(y for x, y in points),
    )


def wire_hits_body(wire: Wire, box: Box, clearance: float = 0.254) -> bool:
    x0, y0, x1, y1 = box
    x0, y0, x1, y1 = x0 - clearance, y0 - clearance, x1 + clearance, y1 + clearance
    eps = 1e-6
    if abs(wire.y1 - wire.y2) < eps:
        return (
            y0 + eps < wire.y1 < y1 - eps
            and max(wire.x1, wire.x2) > x0 + eps
            and min(wire.x1, wire.x2) < x1 - eps
        )
    return (
        x0 + eps < wire.x1 < x1 - eps
        and max(wire.y1, wire.y2) > y0 + eps
        and min(wire.y1, wire.y2) < y1 - eps
    )

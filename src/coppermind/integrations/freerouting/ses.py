"""Parse a Specctra .ses session into Coppermind tracks and vias.

The .ses file is what Freerouting writes after routing. This pure parser reads
the routed ``network_out`` — per-net wires (polyline paths) and vias — honouring
the file's resolution/units, and converts them into domain ``Track``/``Via``
objects ready to apply to a board. No KiCAD, no network.
"""

from __future__ import annotations

from pydantic import BaseModel

from coppermind.domain.models import COPPER_LAYERS, Layer, Point, Track, Via
from coppermind.integrations.freerouting.sexpr import find, find_all, parse

# Specctra unit -> millimetres for one unit of measure.
_UNIT_MM = {"um": 0.001, "mm": 1.0, "inch": 25.4, "mil": 0.0254}


class RouteResult(BaseModel):
    tracks: list[Track] = []
    vias: list[Via] = []


def _scale_mm(resolution: list | None) -> float:
    """mm per resolution-unit, from a (resolution <unit> <value>) node."""
    if not resolution or len(resolution) < 3:
        return 0.001  # default: um with value 1
    unit = str(resolution[1]).lower()
    value = float(resolution[2]) or 1.0
    return _UNIT_MM.get(unit, 0.001) / value


def _layer(name: str) -> Layer:
    try:
        layer = Layer(name)
    except ValueError:
        return Layer.F_CU
    return layer if layer in COPPER_LAYERS else Layer.F_CU


def parse_ses(text: str) -> RouteResult:
    """Parse SES text into routed tracks and vias."""
    tree = parse(text)
    routes = find(tree, "routes")
    if routes is None:
        return RouteResult()
    scale = _scale_mm(find(routes, "resolution"))
    network = find(routes, "network_out")
    if network is None:
        return RouteResult()

    tracks: list[Track] = []
    vias: list[Via] = []
    for net in find_all(network, "net"):
        net_name = str(net[1]) if len(net) > 1 else ""
        for wire in find_all(net, "wire"):
            path = find(wire, "path")
            if not path or len(path) < 4:
                continue
            layer = _layer(str(path[1]))
            width = float(path[2]) * scale
            coords = [float(c) for c in path[3:] if isinstance(c, (int, float))]
            pts = [
                Point(x=coords[i] * scale, y=coords[i + 1] * scale)
                for i in range(0, len(coords) - 1, 2)
            ]
            for a, b in zip(pts, pts[1:]):
                tracks.append(Track(net=net_name, start=a, end=b, width=width, layer=layer))
        for via in find_all(net, "via"):
            nums = [c for c in via[2:] if isinstance(c, (int, float))]
            if len(nums) >= 2:
                vias.append(
                    Via(position=Point(x=nums[0] * scale, y=nums[1] * scale), net=net_name)
                )
    return RouteResult(tracks=tracks, vias=vias)

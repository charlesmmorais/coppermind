"""Write a Coppermind Board as a KiCAD ``.kicad_pcb`` S-expression.

This is what lets the headless ``BatchBackend`` produce a real board file for
``kicad-cli`` DRC/render without a running KiCAD. The writer is pure (string in,
string out) and emits the modern KiCad 9/10 grammar: layer stack, nets,
footprints with pads, copper segments, vias and the board outline on Edge.Cuts.

It is deliberately minimal — enough geometry/connectivity for verification and
rendering, not a full feature-for-feature export. Exact acceptance by a specific
kicad-cli version is covered by the integration job; the structure is unit-tested.
"""

from __future__ import annotations

from coppermind.domain.models import Board, Component, Layer, Track, Via

_LAYER_NAME = {Layer.F_CU: "F.Cu", Layer.B_CU: "B.Cu"}


def _fmt(value: float) -> str:
    """Format a coordinate in mm without trailing noise."""
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _net_index(board: Board) -> dict[str, int]:
    """Map net name -> index. Net 0 is the unconnected net ("")."""
    names = sorted({t.net for t in board.tracks if t.net}
                   | {v.net for v in board.vias if v.net}
                   | {p.net for c in board.components.values() for p in c.pads if p.net}
                   | set(board.nets))
    return {name: i + 1 for i, name in enumerate(names)}


def _footprint(comp: Component, nets: dict[str, int]) -> str:
    lines = [
        f'  (footprint "{comp.footprint or "coppermind:unknown"}"',
        f'    (layer "{_LAYER_NAME.get(comp.layer, "F.Cu")}")',
        f'    (at {_fmt(comp.position.x)} {_fmt(comp.position.y)} {_fmt(comp.rotation)})',
        f'    (property "Reference" "{comp.reference}" (at 0 0 0) (layer "F.SilkS"))',
        f'    (property "Value" "{comp.value}" (at 0 0 0) (layer "F.Fab"))',
    ]
    for pad in comp.pads:
        net_ref = f' (net {nets[pad.net]} "{pad.net}")' if pad.net in nets else ""
        if pad.drill and pad.drill > 0:
            lines.append(
                f'    (pad "{pad.number}" thru_hole circle '
                f'(at {_fmt(pad.offset.x)} {_fmt(pad.offset.y)}) '
                f'(size {_fmt(pad.size.x)} {_fmt(pad.size.y)}) (drill {_fmt(pad.drill)}) '
                f'(layers "*.Cu" "*.Mask"){net_ref})'
            )
        else:
            lines.append(
                f'    (pad "{pad.number}" smd roundrect '
                f'(at {_fmt(pad.offset.x)} {_fmt(pad.offset.y)}) '
                f'(size {_fmt(pad.size.x)} {_fmt(pad.size.y)}) (roundrect_rratio 0.25) '
                f'(layers "{_LAYER_NAME.get(pad.layer, "F.Cu")}"){net_ref})'
            )
    lines.append("  )")
    return "\n".join(lines)


def _segment(track: Track, nets: dict[str, int]) -> str:
    net_idx = nets.get(track.net, 0)
    return (
        f'  (segment (start {_fmt(track.start.x)} {_fmt(track.start.y)}) '
        f'(end {_fmt(track.end.x)} {_fmt(track.end.y)}) '
        f'(width {_fmt(track.width)}) (layer "{_LAYER_NAME.get(track.layer, "F.Cu")}") '
        f'(net {net_idx}))'
    )


def _via(via: Via, nets: dict[str, int]) -> str:
    net_idx = nets.get(via.net, 0)
    return (
        f'  (via (at {_fmt(via.position.x)} {_fmt(via.position.y)}) '
        f'(size {_fmt(via.diameter)}) (drill {_fmt(via.drill)}) '
        f'(layers "F.Cu" "B.Cu") (net {net_idx}))'
    )


def _outline(board: Board) -> list[str]:
    if board.outline is None:
        return []
    o = board.outline
    x0, y0 = o.origin.x, o.origin.y
    x1, y1 = x0 + o.width, y0 + o.height
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    out = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:]):
        out.append(
            f'  (gr_line (start {_fmt(ax)} {_fmt(ay)}) (end {_fmt(bx)} {_fmt(by)}) '
            f'(stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))'
        )
    return out


def board_to_kicad_pcb(board: Board) -> str:
    """Serialize a Board to a KiCAD .kicad_pcb string."""
    nets = _net_index(board)
    lines: list[str] = [
        "(kicad_pcb",
        "  (version 20240108)",
        '  (generator "coppermind")',
        '  (generator_version "0.1")',
        "  (general (thickness 1.6))",
        '  (paper "A4")',
        "  (layers",
        '    (0 "F.Cu" signal)',
        '    (2 "B.Cu" signal)',
        '    (9 "F.SilkS" user)',
        '    (11 "B.SilkS" user)',
        '    (44 "Edge.Cuts" user)',
        '    (49 "F.Fab" user)',
        "  )",
        "  (setup)",
        '  (net 0 "")',
    ]
    for name, idx in sorted(nets.items(), key=lambda kv: kv[1]):
        lines.append(f'  (net {idx} "{name}")')
    lines.extend(_outline(board))
    for comp in board.components.values():
        lines.append(_footprint(comp, nets))
    for track in board.tracks:
        lines.append(_segment(track, nets))
    for via in board.vias:
        lines.append(_via(via, nets))
    lines.append(")")
    return "\n".join(lines) + "\n"

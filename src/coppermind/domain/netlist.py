"""Pin-level netlist derived from component pads (KiCAD-independent).

Once components carry pads with net assignments, connectivity is *by pin* rather
than by net name alone. This powers honest connectivity checks and layout
affinity (which components must sit near each other).
"""

from __future__ import annotations

from coppermind.domain.models import Board


def pin_netlist(board: Board) -> dict[str, list[str]]:
    """Return {net_name: ["REF.PAD", ...]} from every component pad with a net."""
    out: dict[str, list[str]] = {}
    for comp in board.components.values():
        for pad in comp.pads:
            if pad.net:
                out.setdefault(pad.net, []).append(f"{comp.reference}.{pad.number}")
    return {net: sorted(pins) for net, pins in out.items()}


def component_netlist(board: Board) -> dict[str, list[str]]:
    """Return {net_name: [component_ref, ...]} — net affinity for placement."""
    out: dict[str, set[str]] = {}
    for comp in board.components.values():
        for pad in comp.pads:
            if pad.net:
                out.setdefault(pad.net, set()).add(comp.reference)
    return {net: sorted(refs) for net, refs in out.items()}

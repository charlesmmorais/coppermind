"""Layout optimization (pure): wirelength estimate + barycenter placement.

Uses HPWL (half-perimeter wirelength) — the standard quick estimate of routed
length — over a component-level netlist. ``suggest_placement`` performs one
barycenter relaxation step: each movable component moves toward the average
position of the components it shares nets with, which provably does not increase
HPWL for a single star net and is the basis of force-directed placers.
"""

from __future__ import annotations

Pos = tuple[float, float]


def hpwl(positions: dict[str, Pos], netlist: dict[str, list[str]]) -> float:
    """Total half-perimeter wirelength across all nets."""
    total = 0.0
    for refs in netlist.values():
        pts = [positions[r] for r in refs if r in positions]
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def neighbors(netlist: dict[str, list[str]]) -> dict[str, set[str]]:
    """Adjacency: components that share at least one net."""
    adj: dict[str, set[str]] = {}
    for refs in netlist.values():
        for a in refs:
            for b in refs:
                if a != b:
                    adj.setdefault(a, set()).add(b)
    return adj


def suggest_placement(
    positions: dict[str, Pos],
    netlist: dict[str, list[str]],
    fixed: set[str] | None = None,
) -> dict[str, Pos]:
    """One barycenter relaxation: move each movable component to its neighbors' mean."""
    fixed = fixed or set()
    adj = neighbors(netlist)
    new_pos = dict(positions)
    for ref, pos in positions.items():
        if ref in fixed:
            continue
        ns = [positions[n] for n in adj.get(ref, ()) if n in positions]
        if not ns:
            continue
        new_pos[ref] = (sum(p[0] for p in ns) / len(ns), sum(p[1] for p in ns) / len(ns))
    return new_pos

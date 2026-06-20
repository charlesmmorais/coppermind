"""Flatten a hierarchical schematic into a global netlist.

Uses union-find over (sheet-instance-path, local-net) nodes. Within a sheet,
pins on the same local net share a node; a SheetInstance unions the child's port
with the parent net it maps to. The result is the set of globally-connected pins,
named by the net closest to the root (shortest path), so top-level names win.
"""

from __future__ import annotations

from coppermind.schematic.models import Sheet


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[object, object] = {}

    def find(self, x: object) -> object:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: object, b: object) -> None:
        self.parent[self.find(a)] = self.find(b)


def flatten_netlist(root: Sheet) -> dict[str, list[str]]:
    """Return {global_net_name: ["REF.PIN", ...]} for a hierarchical schematic."""
    uf = _UnionFind()
    pins: list[tuple[tuple[int, ...], str, str, str]] = []  # (path, net, symbol, pin)

    def walk(sheet: Sheet, path: tuple[int, ...]) -> None:
        for p in sheet.pins:
            node = (path, p.net)
            uf.find(node)
            pins.append((path, p.net, p.symbol, p.pin))
        for i, inst in enumerate(sheet.subsheets):
            child_path = (*path, i)
            for child_port, parent_net in inst.port_map.items():
                uf.union((child_path, child_port), (path, parent_net))
            walk(inst.sheet, child_path)

    walk(root, ())

    # Group pins by connected component; pick the name with the shallowest path.
    groups: dict[object, list[tuple[tuple[int, ...], str, str, str]]] = {}
    for path, net, sym, pin in pins:
        groups.setdefault(uf.find((path, net)), []).append((path, net, sym, pin))

    out: dict[str, list[str]] = {}
    for members in groups.values():
        name = min(members, key=lambda m: (len(m[0]), m[1]))[1]
        final = name
        suffix = 2
        while final in out:  # avoid collisions between unrelated same-named nets
            final = f"{name}~{suffix}"
            suffix += 1
        out[final] = sorted(f"{sym}.{pin}" for _, _, sym, pin in members)
    return out

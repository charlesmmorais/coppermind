"""Record a fixture JSON from a running KiCAD (via kipy/IPC).

Usage (KiCAD running, IPC API enabled, a board open):
    python scripts/record_kicad_fixture.py > tests/fixtures/my_board.json

Emits the same schema the fake kipy / IPCBackend understand (mm, layer names).
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        from coppermind.backends.ipc_backend import IPCBackend
    except Exception as exc:  # pragma: no cover
        print(f"coppermind not importable: {exc}", file=sys.stderr)
        return 2
    ipc = IPCBackend()
    if not ipc.is_available():  # pragma: no cover
        print("KiCAD IPC unavailable; open KiCAD and enable the IPC API.", file=sys.stderr)
        return 1
    board = ipc.load("recorded")  # pragma: no cover - needs KiCAD
    state = {
        "nets": sorted(board.nets),
        "footprints": [
            {"id": c.id, "reference": c.reference, "value": c.value,
             "footprint": c.footprint, "x": c.position.x, "y": c.position.y,
             "layer": c.layer.value}
            for c in board.components.values()
        ],
        "tracks": [
            {"id": t.id, "net": t.net, "start": [t.start.x, t.start.y],
             "end": [t.end.x, t.end.y], "width": t.width, "layer": t.layer.value}
            for t in board.tracks
        ],
    }
    json.dump(state, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

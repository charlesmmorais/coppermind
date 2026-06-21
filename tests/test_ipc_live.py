"""Live IPC smoke test against a real KiCAD (CI integration job only).

Skipped unless kipy is importable and a KiCAD instance is reachable. This is the
same code path the fake validates, run against the real thing.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _kicad_available() -> bool:
    try:
        from coppermind.backends.ipc_backend import IPCBackend
    except Exception:
        return False
    return IPCBackend().is_available()


@pytest.mark.skipif(not _kicad_available(), reason="no live KiCAD/kipy available")
def test_live_load_returns_board():
    from coppermind.backends.ipc_backend import IPCBackend
    from coppermind.domain.models import Board

    ipc = IPCBackend()
    board = ipc.load("live")
    assert isinstance(board, Board)

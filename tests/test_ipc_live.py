"""Live IPC smoke test against a real KiCAD session.

Installing KiCAD/kipy is not enough to make IPC live: kipy connects lazily, so
constructing ``KiCad()`` (or ``IPCBackend``) can succeed while no KiCAD process
is listening on the IPC socket.  These tests therefore probe the same operation
they need and self-skip unless a board is actually reachable.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _live_board_available() -> bool:
    """Return True only when a live KiCAD IPC session exposes an open board."""
    try:
        from coppermind.backends.ipc_backend import IPCBackend

        IPCBackend().load("_ipc_probe")
    except Exception:
        return False
    return True


@pytest.mark.skipif(
    not _live_board_available(),
    reason="no live KiCAD IPC session with an open board",
)
def test_live_load_returns_board():
    from coppermind.backends.ipc_backend import IPCBackend
    from coppermind.domain.models import Board

    ipc = IPCBackend()
    board = ipc.load("live")
    assert isinstance(board, Board)

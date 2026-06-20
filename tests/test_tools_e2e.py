"""End-to-end exercise of the core tools against the in-memory backend.

This is the Phase-0 acceptance test: create a project, place components, route,
preview, and commit — all reversible, no KiCAD required.
"""

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import core


def fresh_session():
    return Session(backend=MemoryBackend())


def test_full_happy_path():
    s = fresh_session()
    assert core.project_create(s, "LEDBoard", 50, 50)["ok"]

    core.component_place(s, "R1", "R_0805_2012Metric", 10, 10, value="330")
    core.component_place(s, "D1", "LED_0805_2012Metric", 20, 10, value="RED")
    core.net_create(s, "LED1")
    core.net_route(s, "LED1", 10, 10, 20, 10, width_mm=0.3)

    preview = core.design_preview(s)
    assert preview["diff_detail"]["components_added"] == ["D1", "R1"]
    assert preview["would_block"] is False

    result = core.design_commit(s)
    assert result["committed"] is True

    # Persisted in the backend.
    board = s.backend.load("LEDBoard")
    assert set(board.components) == {"R1", "D1"}
    assert len(board.tracks) == 1


def test_commit_blocked_then_rollback():
    s = fresh_session()
    core.project_create(s, "Bad", 50, 50)
    core.component_place(s, "U1", "QFN", 500, 500)  # outside board
    result = core.design_commit(s)
    assert result["committed"] is False
    assert any(v["code"] == "COMPONENT_OUTSIDE_BOARD" for v in result["violations"])

    core.design_rollback(s)
    assert core.design_preview(s)["diff_detail"]["components_added"] == []


def test_render_produces_svg():
    s = fresh_session()
    core.project_create(s, "Vis", 30, 20)
    core.component_place(s, "R1", "R_0805", 10, 10)
    core.design_commit(s)
    svg = s.backend.render(s.document.board)
    assert svg is not None and b"<svg" in svg
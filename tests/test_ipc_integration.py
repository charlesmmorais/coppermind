"""IPC adapter validated end-to-end against the fake kipy (no KiCAD needed).

These exercise the previously-uncovered ``IPCBackend.load/apply/render`` code:
mm↔nm conversion, KIID mapping, and the create/update/remove commit calls — all
driven by a recorded fixture and asserted via the fake board's call journal.
"""

from __future__ import annotations

import pytest

from coppermind.backends.ipc_backend import IPCBackend
from coppermind.domain import operations as ops
from coppermind.domain.models import Point


@pytest.fixture()
def ipc(fake_kipy, fixtures_dir):
    return IPCBackend(headless=True, file_path=str(fixtures_dir / "two_resistors.json"))


def _journal_kinds(board):
    return [entry[0] for entry in board.journal]


def test_load_maps_board_with_units_and_ids(ipc):
    b = ipc.load("two_resistors")
    assert set(b.components) == {"R1", "D1"}
    assert b.components["R1"].position == Point(x=10.0, y=10.0)     # nm -> mm
    assert b.components["R1"].id == "kiid-R1"                       # KIID preserved
    assert b.components["R1"].footprint == "Resistor_SMD:R_0603_1608Metric"
    assert set(b.nets) == {"GND", "VCC", "LED1"}
    assert len(b.tracks) == 1
    assert b.tracks[0].id == "kiid-T1" and b.tracks[0].net == "LED1"
    assert b.tracks[0].width == 0.3                                 # 300000 nm -> mm


def test_apply_add_track_creates_item(ipc):
    after = ipc.load("two_resistors")
    ops.route_track(after, "LED1", (20.0, 10.0), (20.0, 20.0), width=0.25)
    ipc.apply(after)
    board = ipc._board()
    assert "create_items" in _journal_kinds(board)
    assert "push_commit" in _journal_kinds(board)
    # the created kipy track carries the right nm width
    created = [e for e in board.journal if e[0] == "create_items"][-1][1]
    assert any(getattr(it, "width", None) == 250000 for it in created)


def test_apply_move_component_updates(ipc):
    after = ipc.load("two_resistors")
    ops.move_component(after, "R1", 30.0, 30.0)
    ipc.apply(after)
    assert "update_items" in _journal_kinds(ipc._board())


def test_apply_remove_component(ipc):
    after = ipc.load("two_resistors")
    ops.delete_component(after, "D1")
    ipc.apply(after)
    board = ipc._board()
    assert "remove_items" in _journal_kinds(board)
    assert {fp.reference_field.value for fp in board.get_footprints()} == {"R1"}


def test_apply_modify_track_by_id(ipc):
    after = ipc.load("two_resistors")
    after.tracks[0] = after.tracks[0].model_copy(update={"width": 0.5})
    ipc.apply(after)
    assert "update_items" in _journal_kinds(ipc._board())


def test_apply_remove_track_by_id(ipc):
    after = ipc.load("two_resistors")
    after.tracks.clear()
    ipc.apply(after)
    board = ipc._board()
    assert "remove_items_by_id" in _journal_kinds(board)
    assert board.get_tracks() == []


def test_apply_noop_when_identical(ipc):
    after = ipc.load("two_resistors")
    ipc.apply(after)  # no diff
    assert "push_commit" not in _journal_kinds(ipc._board())


def test_render_returns_svg(ipc):
    data = ipc.render(ipc.load("two_resistors"))
    assert data is not None and b"<svg" in data


def test_roundtrip_add_then_reload(ipc):
    after = ipc.load("two_resistors")
    ops.route_track(after, "LED1", (5, 5), (6, 6))
    ipc.apply(after)
    reloaded = ipc.load("two_resistors")
    assert len(reloaded.tracks) == 2   # original + the applied one

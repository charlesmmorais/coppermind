"""Test harness: a faithful in-process fake of the kipy (KiCAD IPC) API.

This is what takes the IPC adapter out of "unvalidated". The fake mimics the
small slice of the kipy surface that ``IPCBackend`` uses, driven by recorded
fixtures (JSON board states under ``tests/fixtures/``). Because ``IPCBackend``
imports kipy *lazily*, the ``fake_kipy`` fixture injects the fake modules into
``sys.modules`` for the duration of a test, so ``load`` / ``apply`` / ``render``
actually execute end-to-end — no KiCAD required.

The same fixtures can be captured from a real KiCAD with
``scripts/record_kicad_fixture.py`` and replayed against live KiCAD in
``tests/test_ipc_live.py`` (marked ``integration``).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
_MM_TO_NM = 1_000_000
_LAYER_NAME_TO_INT = {"F.Cu": 0, "B.Cu": 2}


# --- fake kipy value types -------------------------------------------------

class _Vector2:
    def __init__(self, x: int = 0, y: int = 0) -> None:
        self.x, self.y = int(x), int(y)

    @classmethod
    def from_xy(cls, x: int, y: int) -> "_Vector2":
        return cls(x, y)


class _Field:
    def __init__(self, value: str = "") -> None:
        self.value = value


class _LibraryIdentifier:
    def __init__(self, library: str = "", name: str = "") -> None:
        self.library, self.name = library, name


class _FootprintDef:
    def __init__(self) -> None:
        self.id = _LibraryIdentifier()


_counter = {"n": 0}


def _kiid() -> str:
    _counter["n"] += 1
    return f"fake-kiid-{_counter['n']:04d}"


class _FootprintInstance:
    def __init__(self) -> None:
        self.id = _kiid()
        self.position = _Vector2()
        self.layer = 0
        self.reference_field = _Field()
        self.value_field = _Field()
        self.definition = _FootprintDef()


class _Net:
    def __init__(self, name: str = "") -> None:
        self.name = name


class _Track:
    def __init__(self) -> None:
        self.id = _kiid()
        self.net = _Net()
        self.start = _Vector2()
        self.end = _Vector2()
        self.width = 0
        self.layer = 0


class _Via:
    def __init__(self) -> None:
        self.id = _kiid()
        self.position = _Vector2()
        self.net = _Net()


class _Commit:
    pass


class FakeBoard:
    """Records every mutating call so tests can assert what would hit KiCAD."""

    def __init__(self, state: dict) -> None:
        self.footprints: list[_FootprintInstance] = []
        self.nets: list[_Net] = []
        self.tracks: list[_Track] = []
        self.vias: list[_Via] = []
        self.journal: list[tuple] = []
        self._load_state(state)

    def _load_state(self, state: dict) -> None:
        for name in state.get("nets", []):
            self.nets.append(_Net(name))
        for fp in state.get("footprints", []):
            inst = _FootprintInstance()
            inst.id = fp.get("id", _kiid())
            inst.position = _Vector2(fp["x"] * _MM_TO_NM, fp["y"] * _MM_TO_NM)
            inst.layer = _LAYER_NAME_TO_INT.get(fp.get("layer", "F.Cu"), 0)
            inst.reference_field = _Field(fp["reference"])
            inst.value_field = _Field(fp.get("value", ""))
            lib, _, nm = fp.get("footprint", ":").partition(":")
            inst.definition.id = _LibraryIdentifier(lib, nm)
            self.footprints.append(inst)
        for t in state.get("tracks", []):
            tr = _Track()
            tr.id = t.get("id", _kiid())
            tr.net = _Net(t.get("net", ""))
            tr.start = _Vector2(t["start"][0] * _MM_TO_NM, t["start"][1] * _MM_TO_NM)
            tr.end = _Vector2(t["end"][0] * _MM_TO_NM, t["end"][1] * _MM_TO_NM)
            tr.width = int(t.get("width", 0.25) * _MM_TO_NM)
            tr.layer = _LAYER_NAME_TO_INT.get(t.get("layer", "F.Cu"), 0)
            self.tracks.append(tr)

    # -- reads --
    def get_nets(self): return list(self.nets)
    def get_footprints(self): return list(self.footprints)
    def get_tracks(self): return list(self.tracks)

    def get_items_by_id(self, ids):
        wanted = set(ids)
        return [it for it in (*self.tracks, *self.vias, *self.footprints) if it.id in wanted]

    # -- commit lifecycle --
    def begin_commit(self):
        self.journal.append(("begin_commit",))
        return _Commit()

    def push_commit(self, commit, message=""):
        self.journal.append(("push_commit", message))

    def drop_commit(self, commit):
        self.journal.append(("drop_commit",))

    # -- writes --
    def create_items(self, items):
        for it in items:
            if isinstance(it, _Track):
                self.tracks.append(it)
            elif isinstance(it, _Via):
                self.vias.append(it)
            elif isinstance(it, _FootprintInstance):
                self.footprints.append(it)
        self.journal.append(("create_items", list(items)))
        return list(items)

    def update_items(self, items):
        self.journal.append(("update_items", list(items)))
        return list(items)

    def remove_items(self, items):
        for it in items:
            for bucket in (self.footprints, self.tracks, self.vias):
                if it in bucket:
                    bucket.remove(it)
        self.journal.append(("remove_items", list(items)))

    def remove_items_by_id(self, ids):
        wanted = set(ids)
        for bucket in (self.footprints, self.tracks, self.vias):
            bucket[:] = [it for it in bucket if it.id not in wanted]
        self.journal.append(("remove_items_by_id", list(ids)))

    # -- export --
    def get_as_string(self): return "(kicad_pcb (version 20240101))"

    def export_svg(self, output_path, **kwargs):
        Path(output_path).write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        return None


class FakeKiCad:
    def __init__(self, headless: bool = False, file_path: str | None = None, **kwargs) -> None:
        state = json.loads(Path(file_path).read_text(encoding="utf-8")) if file_path else {}
        self._board = FakeBoard(state)

    def get_board(self): return self._board
    def get_kicad_binary_path(self, name): return f"/usr/bin/{name}"


def _build_modules() -> dict[str, types.ModuleType]:
    kipy = types.ModuleType("kipy")
    kipy.KiCad = FakeKiCad
    geometry = types.ModuleType("kipy.geometry")
    geometry.Vector2 = _Vector2
    board_types = types.ModuleType("kipy.board_types")
    board_types.Net = _Net
    board_types.Track = _Track
    board_types.Via = _Via
    board_types.FootprintInstance = _FootprintInstance
    common_types = types.ModuleType("kipy.common_types")
    common_types.LibraryIdentifier = _LibraryIdentifier
    kipy.geometry = geometry
    kipy.board_types = board_types
    kipy.common_types = common_types
    return {
        "kipy": kipy,
        "kipy.geometry": geometry,
        "kipy.board_types": board_types,
        "kipy.common_types": common_types,
    }


@pytest.fixture()
def fake_kipy():
    """Install the fake kipy into sys.modules for the duration of a test."""
    modules = _build_modules()
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, prev in saved.items():
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES

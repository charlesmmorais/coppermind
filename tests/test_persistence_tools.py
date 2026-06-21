import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.core import component_place, project_create


def _session():
    s = Session(backend=MemoryBackend())
    project_create(s, "P", 50, 40)
    component_place(s, "R1", "R_0603", 10, 10)
    return s


def test_tools_discoverable():
    names = set(REGISTRY.names)
    assert {"project_save", "project_open", "design_export_pcb"} <= names


def test_save_then_open_roundtrip(tmp_path):
    s = _session()
    jp = str(tmp_path / "p.json")
    assert REGISTRY.execute_tool(s, "project_save", {"path": jp})["ok"]
    s2 = Session(backend=MemoryBackend())
    out = REGISTRY.execute_tool(s2, "project_open", {"path": jp})
    assert out["project"] == "P" and out["components"] == 1


def test_export_pcb_writes_file(tmp_path):
    s = _session()
    pcb = str(tmp_path / "p.kicad_pcb")
    out = REGISTRY.execute_tool(s, "design_export_pcb", {"path": pcb})
    assert out["ok"]
    assert open(out["exported"], encoding="utf-8").read().startswith("(kicad_pcb")


def test_export_pcb_rejects_wrong_suffix(tmp_path):
    s = _session()
    with pytest.raises(ValueError):
        REGISTRY.execute_tool(s, "design_export_pcb", {"path": str(tmp_path / "p.txt")})

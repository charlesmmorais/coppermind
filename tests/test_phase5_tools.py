from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.core import component_place, net_create, net_route, project_create


def _session():
    s = Session(backend=MemoryBackend())
    project_create(s, "P", 50, 40)
    component_place(s, "R1", "R_0805", 10, 10, value="10k")
    component_place(s, "R2", "R_0805", 20, 10, value="4k7")
    return s


def test_phase5_tools_discoverable():
    names = set(REGISTRY.names)
    assert {"variant_preview", "variant_apply", "design_placement_report"} <= names
    assert "variant" in REGISTRY.list_categories()


def test_variant_preview_non_mutating():
    s = _session()
    out = REGISTRY.execute_tool(s, "variant_preview", {"overrides": {"R1": {"value": "22k"}, "R2": {"dnp": True}}})
    vals = {c["reference"]: c["value"] for c in out["components"]}
    assert vals == {"R1": "22k"}                 # R2 dropped
    # working board still has R2 (preview did not mutate)
    assert "R2" in s.document.working().components


def test_variant_apply_mutates_working():
    s = _session()
    REGISTRY.execute_tool(s, "variant_apply", {"overrides": {"R2": {"dnp": True}}})
    assert "R2" not in s.document.working().components


def test_placement_report():
    s = _session()
    net_create(s, "N")
    net_route(s, "N", 10, 10, 20, 10, width_mm=0.25)
    rep = REGISTRY.execute_tool(s, "design_placement_report", {})
    assert rep["components"] == 2
    assert rep["total_track_length_mm"] == 10.0

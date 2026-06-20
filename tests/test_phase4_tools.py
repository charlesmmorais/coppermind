from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.core import component_place, design_commit, project_create


def _session():
    s = Session(backend=MemoryBackend())
    project_create(s, "P", 50, 40)
    return s


def test_phase4_tools_discoverable_and_categorized():
    names = set(REGISTRY.names)
    assert {"design_timeline", "design_explain", "supplier_search",
            "supplier_cheapest", "route_check"} <= names
    cats = REGISTRY.list_categories()
    assert "supplier" in cats and "routing" in cats


def test_timeline_tool_after_commit():
    s = _session()
    component_place(s, "R1", "R_0805", 10, 10)
    design_commit(s)
    tl = REGISTRY.execute_tool(s, "design_timeline", {})["timeline"]
    assert len(tl) == 1 and tl[0]["components"] == 1


def test_explain_tool_returns_narrative():
    s = _session()
    component_place(s, "U1", "LQFP-48", 20, 20)
    out = REGISTRY.execute_tool(s, "design_explain", {})
    assert "narrative" in out and "U1" in out["narrative"]


def test_supplier_tools():
    s = _session()
    found = REGISTRY.execute_tool(s, "supplier_search", {"query": "10k"})
    assert found["parts"]
    cheap = REGISTRY.execute_tool(s, "supplier_cheapest", {"query": "10k", "qty": 10})
    assert cheap["cheapest"]["basic"] is True  # basic wins at low qty


def test_route_check_tool():
    s = _session()
    out = REGISTRY.execute_tool(s, "route_check", {"jar_path": "/definitely/missing.jar"})
    assert out["ready"] is False and "runtime" in out

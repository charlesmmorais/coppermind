import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import CORE_TOOLS, DISCOVERY_TOOLS, REGISTRY
from coppermind.tools.core import project_create


def _session_with_project():
    s = Session(backend=MemoryBackend())
    project_create(s, "P", 50, 40)
    return s


def test_routed_tools_are_hidden_from_visible_set():
    visible = {fn.__name__ for fn in CORE_TOOLS + DISCOVERY_TOOLS}
    routed = set(REGISTRY.names)
    assert visible.isdisjoint(routed), "routed tools must not be always-visible"
    assert "wire_add" not in routed
    assert "symbol_add" not in routed
    assert {"component_place", "net_create", "net_route"} <= routed


def test_list_categories_counts():
    cats = REGISTRY.list_categories()
    assert cats["component"] >= 3
    assert "design" in cats and "net" in cats


def test_search_finds_by_keyword():
    hits = REGISTRY.search_tools("undo")
    assert any(h["name"] == "design_undo" for h in hits)


def test_get_schema_lists_parameters():
    schema = REGISTRY.get_tool_schema("component_move")
    assert schema["parameters"] == ["reference", "x_mm", "y_mm"]
    assert schema["category"] == "component"


def test_execute_tool_runs_routed_tool():
    s = _session_with_project()
    REGISTRY.execute_tool(
        s,
        "component_place",
        {"reference": "R1", "footprint": "R_0805", "x_mm": 10, "y_mm": 10},
    )
    out = REGISTRY.execute_tool(
        s,
        "component_move",
        {"reference": "R1", "x_mm": 20, "y_mm": 20},
    )
    assert out["moved"] == "R1"
    listing = REGISTRY.execute_tool(s, "component_list", {})
    assert listing["components"][0]["x"] == 20


def test_unknown_tool_raises():
    s = _session_with_project()
    with pytest.raises(KeyError):
        REGISTRY.get_tool_schema("does_not_exist")
    with pytest.raises(KeyError):
        REGISTRY.execute_tool(s, "does_not_exist", {})

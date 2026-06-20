from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.core import component_place, design_preview, project_create


def _session():
    s = Session(backend=MemoryBackend())
    project_create(s, "P", 50, 40)
    return s


def test_routed_intelligence_tools_discoverable():
    names = set(REGISTRY.names)
    assert {"design_critique", "design_list_rules", "design_explain_rule",
            "design_add_decoupling", "design_add_led"} <= names


def test_execute_critique_and_block_via_registry():
    s = _session()
    component_place(s, "U1", "LQFP-48", 20, 20)
    crit = REGISTRY.execute_tool(s, "design_critique", {})
    assert any(f["code"] == "EE.DECOUPLING.PER_IC" for f in crit["findings"])
    REGISTRY.execute_tool(s, "design_add_decoupling", {"ic_reference": "U1", "cap_reference": "C1"})
    crit2 = REGISTRY.execute_tool(s, "design_critique", {})
    assert not any(f["code"] == "EE.DECOUPLING.PER_IC" for f in crit2["findings"])


def test_list_and_explain_rules():
    s = _session()
    rules = REGISTRY.execute_tool(s, "design_list_rules", {})
    assert rules["kb_version"]
    assert any(r["citation"] == "IPC-2221" for r in rules["rules"])
    explained = REGISTRY.execute_tool(s, "design_explain_rule", {"rule_id": "EE.DECOUPLING.PER_IC"})
    assert explained["rationale"]


def test_preview_includes_advice():
    s = _session()
    component_place(s, "U1", "LQFP-48", 20, 20)
    out = design_preview(s)
    assert "advice" in out
    assert any(a["code"] == "EE.DECOUPLING.PER_IC" for a in out["advice"])

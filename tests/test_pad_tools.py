from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.core import component_place, project_create


def _session():
    s = Session(backend=MemoryBackend())
    project_create(s, "P", 50, 40)
    component_place(s, "U1", "QFN", 10, 10)
    component_place(s, "R1", "R_0603", 30, 10)
    return s


def test_pad_tools_discoverable():
    names = set(REGISTRY.names)
    assert {"component_add_pad", "component_pads", "design_netlist",
            "design_suggest_placement"} <= names


def test_add_pad_and_list_and_netlist():
    s = _session()
    REGISTRY.execute_tool(s, "component_add_pad", {"reference": "U1", "number": "1", "offset_x": 0, "offset_y": 0, "net": "VCC"})
    REGISTRY.execute_tool(s, "component_add_pad", {"reference": "R1", "number": "1", "offset_x": 0, "offset_y": 0, "net": "VCC"})
    pads = REGISTRY.execute_tool(s, "component_pads", {"reference": "U1"})
    assert pads["pads"][0]["net"] == "VCC"
    nl = REGISTRY.execute_tool(s, "design_netlist", {})["netlist"]
    assert nl["VCC"] == ["R1.1", "U1.1"]


def test_suggest_placement_reduces_wirelength():
    s = _session()
    # both pads on the same net so the two parts attract
    REGISTRY.execute_tool(s, "component_add_pad", {"reference": "U1", "number": "1", "offset_x": 0, "offset_y": 0, "net": "N"})
    REGISTRY.execute_tool(s, "component_add_pad", {"reference": "R1", "number": "1", "offset_x": 0, "offset_y": 0, "net": "N"})
    # add a third part far away on the same net to create real wirelength
    component_place(s, "C1", "C_0402", 10, 40)
    REGISTRY.execute_tool(s, "component_add_pad", {"reference": "C1", "number": "1", "offset_x": 0, "offset_y": 0, "net": "N"})
    out = REGISTRY.execute_tool(s, "design_suggest_placement", {})
    assert out["hpwl_after"] <= out["hpwl_before"]
    assert out["suggested_moves"]  # at least one move proposed

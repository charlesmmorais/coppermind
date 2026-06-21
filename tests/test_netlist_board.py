from coppermind.domain import operations as ops
from coppermind.domain.netlist import component_netlist, pin_netlist


def _board():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R_0603", 10, 10)
    ops.add_component(b, "U1", "QFN", 20, 10)
    ops.add_pad(b, "R1", "1", 0, 0, net="VCC")
    ops.add_pad(b, "R1", "2", 1, 0, net="GND")
    ops.add_pad(b, "U1", "VDD", 0, 0, net="VCC")
    ops.add_pad(b, "U1", "VSS", 0, 1, net="GND")
    return b


def test_pin_netlist_groups_pads():
    nl = pin_netlist(_board())
    assert nl["VCC"] == ["R1.1", "U1.VDD"]
    assert nl["GND"] == ["R1.2", "U1.VSS"]


def test_component_netlist_groups_refs():
    cn = component_netlist(_board())
    assert cn["VCC"] == ["R1", "U1"]
    assert cn["GND"] == ["R1", "U1"]


def test_empty_when_no_pad_nets():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R", 1, 1)
    assert pin_netlist(b) == {} and component_netlist(b) == {}

from coppermind.schematic import Sheet, SchPin, SheetInstance, flatten_netlist


def test_local_net_groups_pins():
    sh = Sheet(name="s", pins=[
        SchPin(symbol="R1", pin="1", net="A"),
        SchPin(symbol="R2", pin="2", net="A"),
        SchPin(symbol="R3", pin="1", net="B"),
    ])
    nl = flatten_netlist(sh)
    assert sorted(nl["A"]) == ["R1.1", "R2.2"]
    assert nl["B"] == ["R3.1"]


def test_hierarchy_merges_child_port_with_parent_net():
    reg = Sheet(name="reg", ports=["VOUT", "GND"], pins=[
        SchPin(symbol="C1", pin="1", net="VOUT"),
        SchPin(symbol="R1", pin="1", net="VOUT"),
        SchPin(symbol="C1", pin="2", net="GND"),
    ])
    root = Sheet(name="root",
                 pins=[SchPin(symbol="U1", pin="VDD", net="VCC"),
                       SchPin(symbol="U1", pin="GND", net="GND")],
                 subsheets=[SheetInstance(sheet=reg, port_map={"VOUT": "VCC", "GND": "GND"})])
    nl = flatten_netlist(root)
    assert nl["VCC"] == ["C1.1", "R1.1", "U1.VDD"]   # parent name wins (shallower)
    assert nl["GND"] == ["C1.2", "U1.GND"]


def test_unrelated_same_named_nets_do_not_collide():
    # Two sibling subsheets each with a private local net "N", not wired together.
    a = Sheet(name="a", pins=[SchPin(symbol="RA", pin="1", net="N")])
    b = Sheet(name="b", pins=[SchPin(symbol="RB", pin="1", net="N")])
    root = Sheet(name="root", subsheets=[SheetInstance(sheet=a), SheetInstance(sheet=b)])
    nl = flatten_netlist(root)
    flat = sorted(sum(nl.values(), []))
    assert flat == ["RA.1", "RB.1"]
    assert len(nl) == 2  # kept separate despite same local name

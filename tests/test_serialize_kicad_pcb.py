from coppermind.domain import operations as ops
from coppermind.integrations.freerouting.sexpr import find, find_all, head, parse
from coppermind.serialize import board_to_kicad_pcb


def _board():
    b = ops.create_board("Demo", 50, 40)
    ops.add_component(b, "R1", "Resistor_SMD:R_0603_1608Metric", 10, 10, value="330")
    ops.add_pad(b, "R1", "1", -0.8, 0, net="LED1")
    ops.add_pad(b, "R1", "2", 0.8, 0, net="VCC")
    ops.create_net(b, "LED1")
    ops.route_track(b, "LED1", (10, 10), (20, 10), width=0.3)
    ops.add_via(b, 20, 10, net="LED1")
    return b


def test_output_is_valid_sexpr_with_expected_sections():
    tree = parse(board_to_kicad_pcb(_board()))
    assert head(tree) == "kicad_pcb"
    assert find(tree, "layers") is not None
    assert find(tree, "setup") is not None
    nets = {n[2] for n in find_all(tree, "net")}   # net names (3rd token)
    assert "LED1" in nets and "VCC" in nets
    assert len(find_all(tree, "footprint")) == 1
    assert len(find_all(tree, "segment")) == 1
    assert len(find_all(tree, "via")) == 1
    assert len(find_all(tree, "gr_line")) == 4      # rectangular outline


def test_footprint_has_pads_with_nets():
    tree = parse(board_to_kicad_pcb(_board()))
    fp = find(tree, "footprint")
    pads = find_all(fp, "pad")
    assert {p[1] for p in pads} == {"1", "2"}


def test_empty_board_still_valid():
    tree = parse(board_to_kicad_pcb(ops.create_board("E", 10, 10)))
    assert head(tree) == "kicad_pcb"
    assert find_all(tree, "footprint") == []

from coppermind.domain import operations as ops
from coppermind.verification.checks import Severity, has_blocking, verify


def test_overlapping_pads_different_nets_short_blocks():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R", 10, 10)
    ops.add_component(b, "R2", "R", 30, 10)   # far apart bodies (no body collision)
    ops.add_pad(b, "R1", "1", 0, 0, net="VCC")
    ops.add_pad(b, "R2", "1", -20.0, 0, net="GND")  # abs (10,10) == R1 pad -> short
    v = verify(b)
    short = [x for x in v if x.code == "PAD_SHORT"]
    assert short and short[0].severity == Severity.ERROR
    assert has_blocking(v)


def test_same_net_pads_do_not_short():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R", 10, 10)
    ops.add_component(b, "R2", "R", 30, 10)
    ops.add_pad(b, "R1", "1", 0, 0, net="GND")
    ops.add_pad(b, "R2", "1", -20.0, 0, net="GND")  # overlap but same net
    assert not any(x.code == "PAD_SHORT" for x in verify(b))


def test_single_pad_net_warns():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R", 10, 10)
    ops.add_pad(b, "R1", "1", 0, 0, net="LONELY")
    warns = [x for x in verify(b) if x.code == "SINGLE_PAD_NET"]
    assert warns and warns[0].severity == Severity.WARNING


def test_padless_board_has_no_pad_violations():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R", 10, 10)
    codes = {x.code for x in verify(b)}
    assert "PAD_SHORT" not in codes and "SINGLE_PAD_NET" not in codes

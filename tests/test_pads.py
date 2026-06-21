
from coppermind.domain import operations as ops
from coppermind.domain.models import Component, Pad, Point, pad_absolute_position


def test_pad_defaults():
    p = Pad(number="1")
    assert p.offset == Point(x=0, y=0) and p.net == "" and p.drill == 0.0


def test_add_and_set_pad_net():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "U1", "QFN", 10, 10)
    ops.add_pad(b, "U1", "1", 1.0, 0.0, net="VCC")
    ops.add_pad(b, "U1", "2", -1.0, 0.0)
    assert [p.number for p in b.components["U1"].pads] == ["1", "2"]
    ops.set_pad_net(b, "U1", "2", "GND")
    assert b.components["U1"].pads[1].net == "GND"


def test_add_pad_requires_component():
    b = ops.create_board("b", 50, 40)
    try:
        ops.add_pad(b, "U9", "1", 0, 0)
    except ValueError as e:
        assert "does not exist" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_pad_absolute_position_rotations():
    c = Component(reference="U1", footprint="x", position=Point(x=10, y=10))
    pad = Pad(number="1", offset=Point(x=2, y=0))
    # 0deg
    p0 = pad_absolute_position(c, pad)
    assert (round(p0.x, 6), round(p0.y, 6)) == (12.0, 10.0)
    # 90deg -> offset (2,0) rotates to (0,2)
    c90 = c.model_copy(update={"rotation": 90})
    p90 = pad_absolute_position(c90, pad)
    assert (round(p90.x, 6), round(p90.y, 6)) == (10.0, 12.0)
    # 180deg -> (-2,0)
    c180 = c.model_copy(update={"rotation": 180})
    p180 = pad_absolute_position(c180, pad)
    assert (round(p180.x, 6), round(p180.y, 6)) == (8.0, 10.0)


def test_pads_survive_deep_copy():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "U1", "QFN", 10, 10)
    ops.add_pad(b, "U1", "1", 1, 1, net="N")
    clone = b.copy_deep()
    clone.components["U1"].pads[0].net = "X"
    assert b.components["U1"].pads[0].net == "N"  # base untouched

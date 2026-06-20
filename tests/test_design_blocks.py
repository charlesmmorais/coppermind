import pytest

from coppermind.domain import operations as ops
from coppermind.intelligence import blocks
from coppermind.intelligence.critique import critique


def test_add_decoupling_places_cap_near_ic():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "U1", "LQFP-48", 20, 20)
    res = blocks.add_decoupling(b, "U1", "C1")
    assert res.placed == ["C1"] and res.rule_id == "EE.DECOUPLING.PER_IC"
    assert "C1" in b.components
    # the block resolves the decoupling finding
    assert not any(f.code == "EE.DECOUPLING.PER_IC" for f in critique(b))


def test_add_decoupling_requires_ic():
    b = ops.create_board("b", 50, 40)
    with pytest.raises(ValueError):
        blocks.add_decoupling(b, "U9", "C1")


def test_led_indicator_places_parts_and_net():
    b = ops.create_board("b", 50, 40)
    res = blocks.add_led_indicator(b, "D1", "R1", "BLINK", 10, 10)
    assert set(res.placed) == {"D1", "R1"}
    assert "BLINK" in b.nets
    assert "D1" in b.components and "R1" in b.components

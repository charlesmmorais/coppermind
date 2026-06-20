from coppermind.domain import operations as ops
from coppermind.variants import ComponentOverride, Variant, resolve_variant


def _board():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "R1", "R_0805", 10, 10, value="10k")
    ops.add_component(b, "R2", "R_0805", 20, 10, value="4k7")
    ops.add_component(b, "C1", "C_0402", 30, 10, value="100nF")
    return b


def test_value_override():
    b = _board()
    out = resolve_variant(b, Variant(name="v", overrides={"R1": ComponentOverride(value="22k")}))
    assert out.components["R1"].value == "22k"
    assert b.components["R1"].value == "10k"  # base untouched


def test_dnp_removes_component():
    b = _board()
    out = resolve_variant(b, Variant(name="v", overrides={"R2": ComponentOverride(dnp=True)}))
    assert "R2" not in out.components
    assert "R2" in b.components  # base untouched


def test_footprint_override_and_unknown_ref_ignored():
    b = _board()
    out = resolve_variant(b, Variant(name="v", overrides={
        "C1": ComponentOverride(footprint="C_0603"),
        "Z9": ComponentOverride(value="x"),  # ignored
    }))
    assert out.components["C1"].footprint == "C_0603"
    assert "Z9" not in out.components

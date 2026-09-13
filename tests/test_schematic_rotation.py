"""Pin identity must agree with KiCad, not merely with our own router."""

import pytest

from coppermind.circuit import Pin
from coppermind.schematic.composer import _pin_anchor
from coppermind.schematic.models import (
    Schematic,
    SchLibraryDefinition,
    SchLibrarySymbol,
    SchSymbol,
)
from coppermind.schematic.visual_review import _symbol_bounds
from coppermind.serialize.kicad_sch import _symbol_body_box


@pytest.mark.parametrize(
    "rotation, offset",
    [(0, (1.27, -3.81)), (90, (-3.81, -1.27)), (180, (-1.27, 3.81)), (270, (3.81, 1.27))],
)
def test_asymmetric_common_pin_matches_kicad_sheet_transform(rotation, offset):
    # Both coordinates are nonzero so swapping pin sides cannot hide behind
    # the symmetric body of Device:R. Unit 0 must remain visible in unit 1.
    raw = """(symbol "Test:Offset"
      (symbol "Offset_0_1"
        (pin passive line (at 1.27 3.81 270) (length 1.27)
          (number "1"))))"""
    library = SchLibrarySymbol(
        lib_id="Test:Offset",
        source_path="test.kicad_sym",
        pins=[Pin(number="1", unit=0)],
        definitions=[SchLibraryDefinition(lib_id="Test:Offset", raw_s_expression=raw)],
    )
    symbol = SchSymbol(lib_id=library.lib_id, reference="U1", x=50.8, y=50.8, rotation=rotation)
    schematic = Schematic(
        name="rotation", symbols=[symbol], library_symbols={library.lib_id: library}
    )
    expected = (50.8 + offset[0], 50.8 + offset[1])
    assert _pin_anchor(schematic, "U1", "1") == pytest.approx(expected)
    for box in (_symbol_bounds(schematic, symbol), _symbol_body_box(symbol, library)):
        assert (box[0] + box[2]) / 2 == pytest.approx(expected[0])
        assert (box[1] + box[3]) / 2 == pytest.approx(expected[1])

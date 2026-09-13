import pytest

from coppermind.circuit import ElectricalType, Pin
from coppermind.schematic.models import SchLibraryDefinition, SchLibrarySymbol, SchSymbol
from coppermind.serialize.kicad_sch import _symbol_instance


DEVICE_R = r"""(symbol "Device:R"
  (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
  (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
  (symbol "R_1_1"
    (pin passive line (at 0 3.81 270) (length 1.27)
      (name "" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))
    (pin passive line (at 0 -3.81 90) (length 1.27)
      (name "" (effects (font (size 1.27 1.27))))
      (number "2" (effects (font (size 1.27 1.27)))))))"""

POWER_5V = r"""(symbol "power:+5V"
  (property "Reference" "#PWR" (at 0 -3.81 0) (hide yes)
    (effects (font (size 1.27 1.27))))
  (property "Value" "+5V" (at 0 3.556 0)
    (effects (font (size 1.27 1.27))))
  (symbol "+5V_1_1"
    (pin power_in line (at 0 0 90) (length 0)
      (name "" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))))"""


def _library(lib_id: str, raw: str, pins: list[Pin]) -> SchLibrarySymbol:
    return SchLibrarySymbol(
        lib_id=lib_id,
        source_path="test.kicad_sym",
        pins=pins,
        definitions=[SchLibraryDefinition(lib_id=lib_id, raw_s_expression=raw)],
    )


def _resistor_library() -> SchLibrarySymbol:
    return _library(
        "Device:R",
        DEVICE_R,
        [
            Pin(number="1", electrical_type=ElectricalType.PASSIVE),
            Pin(number="2", electrical_type=ElectricalType.PASSIVE),
        ],
    )


def test_vertical_two_pin_fields_align_to_the_right_with_clearance():
    symbol = SchSymbol(
        lib_id="Device:R",
        reference="R1",
        value="10k",
        x=76.2,
        y=50.8,
    )

    text = _symbol_instance(symbol, "divider", _resistor_library())

    assert '(property "Reference" "R1" (at 81.28 49.53 0)' in text
    assert '(property "Value" "10k" (at 81.28 52.07 0)' in text
    assert text.count("(justify left)") == 2


def test_horizontal_two_pin_fields_are_centered_above_and_below():
    symbol = SchSymbol(
        lib_id="Device:R",
        reference="R1",
        value="10k",
        x=76.2,
        y=50.8,
        rotation=90.0,
    )

    text = _symbol_instance(symbol, "divider", _resistor_library())

    assert '(property "Reference" "R1" (at 76.2 45.72 90)' in text
    assert '(property "Value" "10k" (at 76.2 55.88 90)' in text
    assert "(justify left)" not in text


def test_power_reference_is_hidden_and_supply_value_is_above_the_glyph():
    library = _library(
        "power:+5V",
        POWER_5V,
        [Pin(number="1", electrical_type=ElectricalType.POWER_INPUT)],
    )
    symbol = SchSymbol(
        lib_id="power:+5V",
        reference="#PWR01",
        value="+5V",
        x=76.2,
        y=31.75,
    )

    text = _symbol_instance(symbol, "divider", library)

    assert '(property "Reference" "#PWR01" (at 76.2 29.21 0) (hide yes)' in text
    assert '(property "Value" "+5V" (at 76.2 27.94 0)' in text


@pytest.mark.parametrize("rotation, local_angle", [(0, 0), (90, 90), (180, 0), (270, 90)])
def test_instance_fields_compensate_parent_quarter_turn(rotation, local_angle):
    symbol = SchSymbol(
        lib_id="Device:R", reference="R1", value="10k", x=76.2, y=50.8, rotation=rotation
    )
    text = _symbol_instance(symbol, "flow", _resistor_library())
    if rotation in (90, 270):
        assert f'(property "Reference" "R1" (at 76.2 45.72 {local_angle})' in text
        assert f'(property "Value" "10k" (at 76.2 55.88 {local_angle})' in text
    else:
        assert f'(property "Reference" "R1" (at 81.28 49.53 {local_angle})' in text
        assert f'(property "Value" "10k" (at 81.28 52.07 {local_angle})' in text
        assert text.count("(justify right)" if rotation == 180 else "(justify left)") == 2

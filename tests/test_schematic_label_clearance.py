from coppermind.circuit import ElectricalType, Pin
from coppermind.schematic.models import (
    NetLabel,
    Schematic,
    SchLibraryDefinition,
    SchLibrarySymbol,
    SchSymbol,
    Wire,
)
from coppermind.serialize.kicad_sch import (
    _label_layouts,
    _text_box,
)


DEVICE_R = r'''(symbol "Device:R"
  (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
  (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
  (symbol "R_1_1"
    (pin passive line (at 0 3.81 270) (length 1.27)
      (name "" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))
    (pin passive line (at 0 -3.81 90) (length 1.27)
      (name "" (effects (font (size 1.27 1.27))))
      (number "2" (effects (font (size 1.27 1.27)))))))'''


def _resistor_library() -> SchLibrarySymbol:
    return SchLibrarySymbol(
        lib_id="Device:R",
        source_path="test.kicad_sym",
        pins=[
            Pin(number="1", electrical_type=ElectricalType.PASSIVE),
            Pin(number="2", electrical_type=ElectricalType.PASSIVE),
        ],
        definitions=[
            SchLibraryDefinition(
                lib_id="Device:R",
                raw_s_expression=DEVICE_R,
            )
        ],
    )


def test_label_moves_along_its_net_to_clear_component_fields():
    library = _resistor_library()
    label = NetLabel(text="VOUT", x=25.08, y=20.0)
    schematic = Schematic(
        name="label_fields",
        symbols=[
            SchSymbol(
                lib_id="Device:R",
                reference="R1",
                value="10k",
                x=20.0,
                y=20.0,
            )
        ],
        wires=[Wire(x1=20.0, y1=20.0, x2=45.0, y2=20.0)],
        labels=[label],
        library_symbols={"Device:R": library},
    )

    placement = _label_layouts(schematic, schematic.library_symbols)[label.uuid]

    assert placement.y == 20.0
    assert 20.0 <= placement.x <= 45.0
    assert placement.x != 25.08


def test_label_avoids_unrelated_crossing_wire_without_leaving_its_net():
    label = NetLabel(text="DATA_OUT", x=25.0, y=20.0)
    schematic = Schematic(
        name="label_crossing",
        wires=[
            Wire(x1=10.0, y1=20.0, x2=40.0, y2=20.0),
            Wire(x1=25.0, y1=15.0, x2=25.0, y2=25.0),
        ],
        labels=[label],
    )

    placement = _label_layouts(schematic, {})[label.uuid]

    assert placement.y == 20.0
    assert 10.0 <= placement.x <= 40.0
    assert placement.x != 25.0


def test_adjacent_labels_choose_non_overlapping_sides_or_positions():
    first = NetLabel(text="SENSE_A", x=20.0, y=20.0)
    second = NetLabel(text="SENSE_B", x=20.0, y=21.5)
    schematic = Schematic(
        name="label_pair",
        wires=[
            Wire(x1=10.0, y1=20.0, x2=40.0, y2=20.0),
            Wire(x1=10.0, y1=21.5, x2=40.0, y2=21.5),
        ],
        labels=[first, second],
    )

    placements = _label_layouts(schematic, {})
    first_place = placements[first.uuid]
    second_place = placements[second.uuid]
    first_box = _text_box(first.text, first_place.x, first_place.y, first_place.justify)
    second_box = _text_box(second.text, second_place.x, second_place.y, second_place.justify)

    assert (
        first_box[2] <= second_box[0]
        or second_box[2] <= first_box[0]
        or first_box[3] <= second_box[1]
        or second_box[3] <= first_box[1]
    )

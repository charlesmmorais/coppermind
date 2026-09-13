"""Regressions from the actual PR20 divider/dense visual review."""

from copy import deepcopy

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import _pin_anchor
from coppermind.schematic.incremental import (
    _body_contacts,
    _point_on_wire,
    route_net_incremental,
    validate_incremental_schematic,
)
from coppermind.schematic.models import (
    SchLibraryDefinition,
    SchLibrarySymbol,
    SchSymbol,
    Schematic,
    NetLabel,
    Wire,
)
from coppermind.schematic.symbol_geometry import symbol_graphic_box, wire_hits_body
from coppermind.serialize.kicad_sch import (
    _boxes_overlap,
    _field_boxes,
    _label_layouts,
    _text_box,
    label_clearance_violations,
)
from coppermind.session import Session
from coppermind.tools.core import project_create
from coppermind.tools.circuit import component_add, create_net, connect_pins
from test_neighborhood_reflow_v3 import DEVICE_LIB


def test_sense_escapes_real_pins_without_crossing_r7_r8_or_moving_symbols(tmp_path):
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB)
    session = Session(backend=MemoryBackend(), symbol_resolver=SymbolResolver([tmp_path]))
    project_create(session, "dense_body", 180, 110)
    for ref in ("R1", "R7", "R8", "R9"):
        component_add(session, ref, "Device:R", value="10k")
    sch = session.require_schematic()
    for ref, at in {
        "R1": (25.4, 25.4, 0),
        "R7": (45.72, 63.5, 0),
        "R8": (63.5, 66.04, 0),
        "R9": (30.48, 60.96, 90),
    }.items():
        symbol = next(s for s in sch.symbols if s.reference == ref)
        symbol.x, symbol.y, symbol.rotation = at
    circuit = session.require_circuit()
    for net, pins in {"VIN": ["R1.1", "R9.1"], "SENSE": ["R7.2", "R8.1", "R9.2"]}.items():
        create_net(session, net)
        connect_pins(session, net, pins)
    route_net_incremental(circuit, sch, "VIN")
    original_symbols = deepcopy(sch.symbols)
    original_wires = deepcopy(sch.wires)
    # The previously accepted trunk passed through R7 and along R8's body edge.
    sch.wires.append(Wire(x1=34.29, y1=63.5, x2=63.5, y2=63.5, net="SENSE"))
    assert set(_body_contacts(sch)) == {("SENSE", "R7"), ("SENSE", "R8")}
    assert validate_incremental_schematic(circuit, sch, run_external=False)["blocking"]
    route_net_incremental(circuit, sch, "SENSE")
    assert _body_contacts(sch) == []
    assert not any(
        wire_hits_body(w, box, clearance=0)
        for w in sch.wires
        for box in _field_boxes(sch, sch.library_symbols)
    )
    assert original_symbols == sch.symbols
    assert original_wires == [w for w in sch.wires if w.net == "VIN"]
    assert _pin_anchor(sch, "R7", "2") == pytest.approx((45.72, 67.31))
    for ref, pin in [("R7", "2"), ("R8", "1"), ("R9", "2")]:
        anchor = _pin_anchor(sch, ref, pin)
        assert any(_point_on_wire(anchor, w) for w in sch.wires if w.net == "SENSE")
    validation = validate_incremental_schematic(circuit, sch, run_external=False)
    assert validation["blocking"] is False, validation


def _connector():
    # Pin anchor is left of the body. A pin-only box misses the rectangle.
    raw = """(symbol "Connector_Generic:Conn_01x01"
      (symbol "Conn_01x01_0_1"
        (rectangle (start -1.27 -1.27) (end 1.27 1.27)))
      (symbol "Conn_01x01_1_1"
        (pin passive line (at -5.08 0 0) (length 3.81) (number "1"))))"""
    return SchLibrarySymbol(
        lib_id="Connector_Generic:Conn_01x01",
        source_path="fixture",
        definitions=[
            SchLibraryDefinition(lib_id="Connector_Generic:Conn_01x01", raw_s_expression=raw)
        ],
    )


def test_gnd_label_clears_connector_graphics_and_remains_on_own_wire():
    library = _connector()
    symbol = SchSymbol(lib_id=library.lib_id, reference="J2", value="RETURN", x=25.4, y=111.76)
    sch = Schematic(
        name="divider_label",
        symbols=[symbol],
        library_symbols={library.lib_id: library},
        wires=[
            Wire(x1=20.32, y1=111.76, x2=22.86, y2=111.76, net="GND"),
            Wire(x1=22.86, y1=85.09, x2=22.86, y2=111.76, net="GND"),
        ],
        labels=[NetLabel(text="GND", x=22.86, y=111.76, net="GND")],
    )
    before = sch.model_dump()
    placement = _label_layouts(sch, sch.library_symbols)[sch.labels[0].uuid]
    actual_body = (24.13, 110.49, 26.67, 113.03)
    assert symbol_graphic_box(symbol, library) == pytest.approx(actual_body)
    assert not _boxes_overlap(
        actual_body, _text_box("GND", placement.x, placement.y, placement.justify)
    )
    assert any(_point_on_wire((placement.x, placement.y), w) for w in sch.wires)
    assert label_clearance_violations(sch) == []
    assert sch.model_dump() == before


def test_unsatisfiable_label_clearance_is_reported():
    library = _connector()
    sch = Schematic(
        name="blocked_label",
        library_symbols={library.lib_id: library},
        symbols=[SchSymbol(lib_id=library.lib_id, reference="J2", x=25.4, y=25.4)],
        labels=[NetLabel(text="GND", x=25.4, y=25.4, net="GND")],
    )
    assert label_clearance_violations(sch)[0]["type"] == "LABEL_CLEARANCE_COLLISION"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_graphic_box_includes_common_unit_and_correct_rotation(rotation):
    library = _connector()
    symbol = SchSymbol(lib_id=library.lib_id, reference="J2", x=50.8, y=50.8, rotation=rotation)
    assert symbol_graphic_box(symbol, library) == pytest.approx((49.53, 49.53, 52.07, 52.07))


@pytest.mark.parametrize(
    "rotation, box",
    [
        (0, (12, 9, 14, 13)),
        (90, (9, 6, 13, 8)),
        (180, (6, 7, 8, 11)),
        (270, (7, 12, 11, 14)),
    ],
)
def test_asymmetric_common_body_ignores_other_units_and_pin_extents(rotation, box):
    raw = """(symbol "Test:Body"
      (symbol "Body_0_1" (rectangle (start 2 -3) (end 4 1)))
      (symbol "Body_2_1" (rectangle (start -100 -100) (end 100 100)))
      (symbol "Body_1_1" (pin passive line (at 20 30 0) (length 10) (number "1"))))"""
    library = SchLibrarySymbol(
        lib_id="Test:Body",
        source_path="fixture",
        definitions=[SchLibraryDefinition(lib_id="Test:Body", raw_s_expression=raw)],
    )
    symbol = SchSymbol(lib_id="Test:Body", reference="U1", x=10, y=10, rotation=rotation)
    assert symbol_graphic_box(symbol, library) == pytest.approx(box)


def test_label_on_safe_crossing_cannot_follow_the_other_net():
    from coppermind.serialize.kicad_sch import _label_network

    label = NetLabel(text="VIN", x=20, y=20, net="VIN")
    sch = Schematic(
        name="owned_crossing",
        labels=[label],
        wires=[
            Wire(x1=20, y1=10, x2=20, y2=30, net="VIN"),
            Wire(x1=10, y1=20, x2=30, y2=20, net="GND"),
        ],
    )
    assert _label_network(sch, label) == {0}
    placed = _label_layouts(sch, {})[label.uuid]
    assert _point_on_wire((placed.x, placed.y), sch.wires[0])


def test_nearby_body_detour_preserves_horizontal_flow(tmp_path):
    from coppermind.tools.flow_orientation import component_orient_flow

    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB)
    raw = (
        _connector()
        .definitions[0]
        .raw_s_expression.replace('"Connector_Generic:Conn_01x01"', '"Conn_01x01"')
    )
    (tmp_path / "Connector_Generic.kicad_sym").write_text(
        "(kicad_symbol_lib (version 20231120) (generator test) " + raw + ")"
    )
    session = Session(backend=MemoryBackend(), symbol_resolver=SymbolResolver([tmp_path]))
    project_create(session, "horizontal_body", 160, 90)
    component_add(session, "J1", "Connector_Generic:Conn_01x01", value="INPUT")
    for ref in ("R1", "R2"):
        component_add(session, ref, "Device:R", value="10k")
    sch = session.require_schematic()
    for symbol, x, angle in zip(sch.symbols, [25.4, 55.88, 81.28], [0, 0, 90]):
        symbol.x, symbol.y, symbol.rotation = x, 25.4, angle
    external = [s.model_dump() for s in sch.symbols if s.reference != "R1"]
    for net, pins in {"VIN": ["J1.1", "R1.1"], "N12": ["R1.2", "R2.1"]}.items():
        create_net(session, net)
        connect_pins(session, net, pins)
    result = component_orient_flow(session, "R1")
    assert result["rotation"] == 90, result
    assert result["route_length_mm"] < 60  # no coarse 10.16mm outer-lane excursion
    sch = session.require_schematic()
    assert external == [s.model_dump() for s in sch.symbols if s.reference != "R1"]
    assert _body_contacts(sch) == []

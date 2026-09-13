from __future__ import annotations

from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import _pin_anchor
from coppermind.schematic.incremental import validate_incremental_schematic
from coppermind.session import Session
from coppermind.tools.circuit import (
    component_add,
    component_place_relative,
    connect_incremental,
    create_net,
)
from coppermind.tools.core import project_create
from coppermind.tools.flow_orientation import component_orient_flow
from coppermind.tools.registry import REGISTRY


DEVICE_LIB = r'''(kicad_symbol_lib
  (version 20231120)
  (generator kicad_symbol_editor)
  (symbol "R"
    (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
    (symbol "R_0_1"
      (rectangle (start -1.016 -2.54) (end 1.016 2.54)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))
    )
  )
)'''


def _session(tmp_path: Path) -> Session:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    return Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )


def _axis(session: Session, reference: str) -> str:
    schematic = session.require_schematic()
    first = _pin_anchor(schematic, reference, "1")
    second = _pin_anchor(schematic, reference, "2")
    assert first is not None and second is not None
    return "horizontal" if abs(first[0] - second[0]) > abs(first[1] - second[1]) else "vertical"


def _add_resistor(session: Session, reference: str, value: str = "10k") -> None:
    component_add(session, reference, "Device:R", value=value)


def test_flow_orientation_aligns_horizontal_series_chain(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "flow_chain", 160, 100)
    for ref, value in (("R1", "10k"), ("R2", "22k"), ("R3", "47k")):
        _add_resistor(session, ref, value)

    component_place_relative(session, "R2", "R1", "right", 30.48)
    component_place_relative(session, "R3", "R2", "right", 30.48)
    create_net(session, "N12")
    create_net(session, "N23")
    connect_incremental(session, "N12", ["R1.2", "R2.1"])
    connect_incremental(session, "N23", ["R2.2", "R3.1"])

    results = [component_orient_flow(session, ref) for ref in ("R1", "R2", "R3")]

    assert [_axis(session, ref) for ref in ("R1", "R2", "R3")] == [
        "horizontal",
        "horizontal",
        "horizontal",
    ]
    assert all(result["display_axis"] == "horizontal" for result in results)
    assert all(result["preferred_axis"] == "horizontal" for result in results)

    validation = validate_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=False,
    )
    assert validation["blocking"] is False


def test_flow_orientation_keeps_vertical_branch_vertical(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "vertical_chain", 120, 100)
    _add_resistor(session, "R1")
    _add_resistor(session, "R2", "20k")
    component_place_relative(session, "R2", "R1", "below", 30.48)
    create_net(session, "MID")
    connect_incremental(session, "MID", ["R1.2", "R2.1"])

    component_orient_flow(session, "R1")
    component_orient_flow(session, "R2")

    assert _axis(session, "R1") == "vertical"
    assert _axis(session, "R2") == "vertical"


def test_flow_orientation_preserves_unrelated_net_geometry(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "flow_isolation", 180, 120)
    for ref in ("R1", "R2", "R3", "R4"):
        _add_resistor(session, ref)

    component_place_relative(session, "R2", "R1", "right", 30.48)
    component_place_relative(session, "R3", "R1", "below", 50.8)
    component_place_relative(session, "R4", "R3", "right", 30.48)
    create_net(session, "FLOW")
    create_net(session, "ISO")
    connect_incremental(session, "FLOW", ["R1.2", "R2.1"])
    connect_incremental(session, "ISO", ["R3.2", "R4.1"])

    before = [
        wire.model_dump()
        for wire in session.require_schematic().wires
        if wire.net == "ISO"
    ]
    component_orient_flow(session, "R1")
    after = [
        wire.model_dump()
        for wire in session.require_schematic().wires
        if wire.net == "ISO"
    ]

    assert before == after
    assert _axis(session, "R1") == "horizontal"


def test_flow_orientation_tools_are_routed():
    assert "component_orient_flow" in REGISTRY.names
    assert "component_place_flow" in REGISTRY.names

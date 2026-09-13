from __future__ import annotations

from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.incremental import validate_incremental_schematic
from coppermind.session import Session
from coppermind.tools.circuit import (
    component_add,
    component_place_relative,
    connect_pins,
    create_net,
)
from coppermind.tools.core import project_create
from coppermind.tools.flow_orientation import component_orient_auto
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


def _symbol_rotation(session: Session, reference: str) -> float:
    return next(
        symbol.rotation
        for symbol in session.require_schematic().symbols
        if symbol.reference == reference
    )


def _add_chain(session: Session, vertical: bool) -> None:
    project_create(session, "flow", 140, 100)
    for reference in ("R1", "R2", "R3"):
        component_add(session, reference, "Device:R", value="10k")

    if vertical:
        component_place_relative(session, "R2", "R1", "below", 25.4, lock=False)
        component_place_relative(session, "R3", "R2", "below", 25.4, lock=False)
    else:
        component_place_relative(session, "R2", "R1", "right", 25.4, lock=False)
        component_place_relative(session, "R3", "R2", "right", 25.4, lock=False)

    create_net(session, "N12")
    create_net(session, "N23")
    connect_pins(session, "N12", ["R1.2", "R2.1"])
    connect_pins(session, "N23", ["R2.2", "R3.1"])


def test_flow_orientation_rotates_two_pin_part_into_horizontal_signal_flow(tmp_path: Path):
    session = _session(tmp_path)
    _add_chain(session, vertical=False)

    result = component_orient_auto(session, "R2")

    assert result["ok"] is True
    assert result["chosen_rotation"] == 270.0
    assert _symbol_rotation(session, "R2") == 270.0
    assert result["flow_penalty"] < next(
        candidate["flow_penalty"]
        for candidate in result["candidates"]
        if candidate.get("ok") and candidate["rotation"] == 0.0
    )
    validation = validate_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=False,
    )
    assert validation["blocking"] is False


def test_flow_orientation_keeps_vertical_part_aligned_top_to_bottom(tmp_path: Path):
    session = _session(tmp_path)
    _add_chain(session, vertical=True)

    result = component_orient_auto(session, "R2")

    assert result["chosen_rotation"] == 0.0
    assert _symbol_rotation(session, "R2") == 0.0
    assert result["flow_penalty"] == 0.0


def test_flow_orientation_tools_are_discoverable():
    assert "component_orient_auto" in REGISTRY.names
    assert "component_place_flow_auto" in REGISTRY.names

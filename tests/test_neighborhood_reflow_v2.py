from __future__ import annotations

from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.incremental import route_net_incremental, validate_incremental_schematic
from coppermind.session import Session
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import project_create
from coppermind.tools.neighborhood_reflow_v2 import component_reflow_neighborhood


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


def _set_position(session: Session, reference: str, x: float, y: float) -> None:
    symbol = next(item for item in session.require_schematic().symbols if item.reference == reference)
    symbol.x = x
    symbol.y = y


def test_reflow_v2_shortens_late_component_focus_nets(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "focus_reflow", 180, 110)
    for name in ("VIN", "VOUT", "SENSE"):
        create_net(session, name)

    for reference, value in (
        ("R1", "10k"),
        ("R7", "4.7k"),
        ("R8", "1k"),
        ("R9", "100k"),
        ("R99", "1M"),
    ):
        component_add(session, reference, "Device:R", value=value)

    _set_position(session, "R1", 50.8, 50.8)
    _set_position(session, "R7", 50.8, 88.9)
    _set_position(session, "R8", 50.8, 127.0)
    _set_position(session, "R9", 203.2, 127.0)
    _set_position(session, "R99", 254.0, 165.1)

    connect_pins(session, "VIN", ["R1.1", "R9.1"])
    connect_pins(session, "VOUT", ["R1.2", "R7.1"])
    connect_pins(session, "SENSE", ["R7.2", "R8.1", "R9.2"])

    circuit = session.require_circuit()
    schematic = session.require_schematic()
    for name in ("VOUT", "SENSE", "VIN"):
        route_net_incremental(circuit, schematic, name)

    frozen_before = next(
        (item.x, item.y) for item in schematic.symbols if item.reference == "R99"
    )
    r9_before = next(
        (item.x, item.y) for item in schematic.symbols if item.reference == "R9"
    )

    result = component_reflow_neighborhood(
        session,
        "R9",
        max_components=4,
        passes=2,
        gap_mm=25.4,
        min_improvement=1.0,
    )

    assert result["ok"] is True
    assert result["improved"] is True
    assert result["target_first"] is True
    assert set(result["focus_nets"]) == {"SENSE", "VIN"}
    assert result["focus_route_length_mm"] < result["baseline_focus_route_length_mm"]
    # The deliberately stranded R9 must improve materially, not just by one grid step.
    assert result["focus_route_gain_mm"] >= 25.4
    assert "R9" in result["moved_components"]
    assert result["target_slot_candidates"] > 0
    assert result["target_to"] != result["target_from"]

    r9_after = next(
        (item.x, item.y)
        for item in session.require_schematic().symbols
        if item.reference == "R9"
    )
    assert r9_after != r9_before

    frozen_after = next(
        (item.x, item.y)
        for item in session.require_schematic().symbols
        if item.reference == "R99"
    )
    assert frozen_after == frozen_before

    validation = validate_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=False,
    )
    assert validation["blocking"] is False
    assert validation["semantic_violations"] == []

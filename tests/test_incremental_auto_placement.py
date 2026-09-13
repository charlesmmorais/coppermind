from __future__ import annotations

from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.session import Session
from coppermind.tools.auto_placement import component_place_auto
from coppermind.tools.circuit import component_add, connect_incremental, connect_pins, create_net
from coppermind.tools.core import project_create
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


def _wire_dump(session: Session, net: str) -> list[dict]:
    return [
        wire.model_dump()
        for wire in session.require_schematic().wires
        if wire.net == net
    ]


def test_auto_placement_prefers_shorter_connected_direction(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "auto_place", 120, 100)
    create_net(session, "SIG")
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "R2", "Device:R", value="10k")
    connect_incremental(session, "SIG", ["R1.2", "R2.1"])

    result = component_place_auto(session, "R2", "R1", gap_mm=25.4)

    assert result["ok"] is True
    assert result["chosen_direction"] == "below"
    assert result["chosen_gap_mm"] in {20.32, 25.4, 38.1}
    assert result["locked"] is True
    assert result["rerouted_nets"] == ["SIG"]
    assert len(result["candidates"]) == 12
    assert {item["gap_mm"] for item in result["candidates"]} == {20.32, 25.4, 38.1}
    assert all("score" in item for item in result["candidates"] if item["ok"])

    r1 = next(symbol for symbol in session.require_schematic().symbols if symbol.reference == "R1")
    r2 = next(symbol for symbol in session.require_schematic().symbols if symbol.reference == "R2")
    assert r2.x == r1.x
    assert r2.y > r1.y


def test_auto_placement_rejects_candidates_outside_sheet_margin(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "auto_place_bounds", 120, 100)
    create_net(session, "SIG")
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "R2", "Device:R", value="10k")
    connect_pins(session, "SIG", ["R1.2", "R2.1"])

    result = component_place_auto(session, "R2", "R1", gap_mm=25.4)

    above = [item for item in result["candidates"] if item["direction"] == "above"]
    assert len(above) == 3
    assert all(item["ok"] is False for item in above)
    assert all("leaves usable A4 sheet area" in item["error"] for item in above)
    assert result["chosen_direction"] != "above"

    target = next(
        symbol for symbol in session.require_schematic().symbols if symbol.reference == "R2"
    )
    assert target.x >= 12.7
    assert target.y >= 12.7


def test_auto_placement_routes_semantic_only_connection(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "auto_place_semantic", 120, 100)
    create_net(session, "SIG")
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "R2", "Device:R", value="10k")

    # Declare electrical intent without materializing geometry at the temporary
    # component position. Auto placement must place and route it atomically.
    connect_pins(session, "SIG", ["R1.2", "R2.1"])
    assert _wire_dump(session, "SIG") == []

    result = component_place_auto(session, "R2", "R1", gap_mm=25.4)

    assert result["ok"] is True
    assert result["rerouted_nets"] == ["SIG"]
    assert _wire_dump(session, "SIG")


def test_auto_placement_handles_multiple_unrouted_nets(tmp_path: Path):
    """Regression for the MCP demo: N1 must not be routed at R3's temp position."""
    session = _session(tmp_path)
    project_create(session, "auto_place_multi", 160, 120)
    for net in ("N1", "N2", "N3"):
        create_net(session, net)
    for reference in ("R1", "R2", "R3"):
        component_add(session, reference, "Device:R", value="10k")

    connect_pins(session, "N2", ["R1.2", "R2.1"])
    r2 = component_place_auto(session, "R2", "R1", gap_mm=25.4)
    assert r2["ok"] is True

    connect_pins(session, "N3", ["R2.2", "R3.1"])
    connect_pins(session, "N1", ["R1.1", "R3.2"])
    assert _wire_dump(session, "N1") == []
    assert _wire_dump(session, "N3") == []

    r3 = component_place_auto(session, "R3", "R2", gap_mm=25.4)

    assert r3["ok"] is True
    assert r3["rerouted_nets"] == ["N1", "N3"]
    assert _wire_dump(session, "N1")
    assert _wire_dump(session, "N3")


def test_auto_placement_preserves_unrelated_net_geometry(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "auto_place_preserve", 180, 100)
    for net in ("A", "B"):
        create_net(session, net)
    for reference in ("R1", "R2", "R3", "R4"):
        component_add(session, reference, "Device:R", value="10k")

    connect_incremental(session, "A", ["R1.2", "R2.1"])
    connect_incremental(session, "B", ["R3.2", "R4.1"])
    b_before = _wire_dump(session, "B")
    assert b_before

    result = component_place_auto(session, "R2", "R1", gap_mm=25.4)

    assert result["ok"] is True
    assert _wire_dump(session, "B") == b_before
    assert result["rerouted_nets"] == ["A"]


def test_auto_placement_is_progressively_discoverable():
    schema = REGISTRY.get_tool_schema("component_place_auto")
    assert schema["category"] == "component"
    assert schema["parameters"] == [
        "reference",
        "anchor",
        "gap_mm",
        "directions",
        "lock",
        "force",
    ]

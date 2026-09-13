from __future__ import annotations

from pathlib import Path

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.incremental import route_net_incremental, validate_incremental_schematic
from coppermind.session import Session
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import project_create
from coppermind.tools.flow_orientation import component_orient_flow
from coppermind.tools.neighborhood_reflow_v3 import component_reflow_neighborhood
from coppermind.tools.registry import REGISTRY


DEVICE_LIB = r"""(kicad_symbol_lib
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
)"""


def _session(tmp_path: Path) -> Session:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    return Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )


def _set_position(session: Session, reference: str, x: float, y: float) -> None:
    symbol = next(
        item for item in session.require_schematic().symbols if item.reference == reference
    )
    symbol.x = x
    symbol.y = y


def test_v4_target_bridge_reroutes_neighborhood_without_moving_other_symbols(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "dense_target_bridge", 180, 110)
    for name in ("VIN", "VOUT", "FB", "SENSE", "GND"):
        create_net(session, name)

    values = {
        "R1": "10k",
        "R2": "20k",
        "R3": "47k",
        "R4": "100k",
        "R5": "10k",
        "R6": "10k",
        "R7": "4.7k",
        "R8": "1k",
        "R9": "100k",
    }
    for reference, value in values.items():
        component_add(session, reference, "Device:R", value=value)

    positions = {
        "R1": (60.96, 25.4),
        "R4": (96.52, 25.4),
        "R6": (132.08, 25.4),
        "R7": (20.32, 55.88),
        "R2": (60.96, 55.88),
        "R3": (96.52, 55.88),
        "R5": (132.08, 55.88),
        "R8": (35.56, 91.44),
        "R9": (165.10, 96.52),
    }
    for reference, (x, y) in positions.items():
        _set_position(session, reference, x, y)

    connect_pins(session, "VIN", ["R1.1", "R9.1"])
    connect_pins(session, "VOUT", ["R1.2", "R2.1", "R3.1", "R4.1", "R7.1"])
    connect_pins(session, "FB", ["R4.2", "R5.1", "R6.1"])
    connect_pins(session, "SENSE", ["R7.2", "R8.1", "R9.2"])
    connect_pins(session, "GND", ["R2.2", "R3.2", "R5.2", "R6.2", "R8.2"])

    # FB is outside R9's four-component semantic neighborhood, so preserve a
    # valid pre-existing route for it while the other neighborhood nets reroute.
    route_net_incremental(session.require_circuit(), session.require_schematic(), "FB")

    before = {
        symbol.reference: (symbol.x, symbol.y) for symbol in session.require_schematic().symbols
    }
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
    assert result["strategy"] == "lexicographic-target-bridge"
    assert set(result["focus_nets"]) == {"SENSE", "VIN"}
    assert result["focus_route_gain_mm"] >= result["required_focus_gain_mm"] - 1e-6
    assert result["target_to"] != result["target_from"]
    assert result["routable_candidates"] > 0

    after = {
        symbol.reference: (symbol.x, symbol.y) for symbol in session.require_schematic().symbols
    }
    for reference in before:
        if reference != "R9":
            assert after[reference] == before[reference]

    validation = validate_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=False,
    )
    assert validation["blocking"] is False
    assert validation["semantic_violations"] == []

    # Orient the dense target after reflow while retaining accepted placement,
    # the entire electrical graph and all non-focus route geometry.
    schematic = session.require_schematic()
    before_symbols = {s.reference: s.model_dump() for s in schematic.symbols if s.reference != "R9"}
    before_nets = session.require_circuit().model_dump()["nets"]
    before_wires = [w.model_dump() for w in schematic.wires if w.net not in {"VIN", "SENSE"}]
    focus_length_before = sum(
        abs(w.x2 - w.x1) + abs(w.y2 - w.y1) for w in schematic.wires if w.net in {"VIN", "SENSE"}
    )
    oriented = component_orient_flow(session, "R9")
    assert {c["rotation"] for c in oriented["candidates"]} == {0, 90, 180, 270}
    schematic = session.require_schematic()
    focus_length_after = sum(
        abs(w.x2 - w.x1) + abs(w.y2 - w.y1) for w in schematic.wires if w.net in {"VIN", "SENSE"}
    )
    assert focus_length_before > 0
    assert focus_length_after == pytest.approx(oriented["route_length_mm"], abs=0.002)
    assert before_symbols == {
        s.reference: s.model_dump() for s in schematic.symbols if s.reference != "R9"
    }
    assert before_nets == session.require_circuit().model_dump()["nets"]
    assert before_wires == [
        w.model_dump() for w in schematic.wires if w.net not in {"VIN", "SENSE"}
    ]
    assert (
        validate_incremental_schematic(session.require_circuit(), schematic, run_external=False)[
            "blocking"
        ]
        is False
    )


def test_registry_uses_target_bridge_reflow():
    schema = REGISTRY.get_tool_schema("component_reflow_neighborhood")
    assert schema["category"] == "component"
    assert "max_components" in schema["parameters"]

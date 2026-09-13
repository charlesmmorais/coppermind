from __future__ import annotations

from pathlib import Path

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic import incremental
from coppermind.schematic.models import Schematic, Wire
from coppermind.session import Session
from coppermind.tools.circuit import (
    component_add,
    component_place_relative,
    connect_incremental,
    connect_pins,
    create_net,
    schematic_checkpoint,
    schematic_export_current,
)
from coppermind.tools.core import project_create
from coppermind.tools.registry import REGISTRY


DEVICE_LIB = r'''(kicad_symbol_lib
  (version 20231120)
  (generator kicad_symbol_editor)
  (symbol "R"
    (property "Reference" "R" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_0_1"
      (rectangle (start -2.54 1.016) (end 2.54 -1.016)
        (stroke (width 0) (type default)) (fill (type none))))
    (symbol "R_1_1"
      (pin passive line (at -5.08 0 0) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 5.08 0 180) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "C"
    (property "Reference" "C" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "C_1_1"
      (pin passive line (at -2.54 0 0) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 2.54 0 180) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))))
)'''


def _session(tmp_path: Path) -> Session:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    return Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )


def test_incremental_tools_are_routed_not_always_visible():
    assert "component_place_relative" in REGISTRY.names
    assert "component_freeze_placement" in REGISTRY.names
    assert "connect_incremental" in REGISTRY.names
    assert "schematic_checkpoint" in REGISTRY.names
    assert "schematic_export_current" in REGISTRY.names


def test_place_relative_moves_only_target_and_locks_it(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "C1", "Device:C", value="100n")

    sch = session.require_schematic()
    r1 = next(item for item in sch.symbols if item.reference == "R1")
    c1 = next(item for item in sch.symbols if item.reference == "C1")
    r1_before = (r1.x, r1.y)

    result = component_place_relative(
        session,
        "C1",
        "R1",
        direction="right",
        gap_mm=25.4,
    )

    assert result["locked"] is True
    assert (r1.x, r1.y) == r1_before
    assert c1.x == r1.x + 25.4
    assert c1.y == r1.y
    assert session.require_circuit().components["C1"].properties["placement_locked"] == "true"

    with pytest.raises(ValueError, match="placement is locked"):
        component_place_relative(session, "C1", "R1", direction="below")


def test_force_reposition_reroutes_only_impacted_net(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R")
    component_add(session, "C1", "Device:C")
    component_place_relative(session, "C1", "R1", "right", 25.4)
    create_net(session, "A")
    connect_incremental(session, "A", ["R1.2", "C1.1"])

    before = [wire.model_dump() for wire in session.require_schematic().wires]
    moved = component_place_relative(
        session,
        "C1",
        "R1",
        direction="below",
        gap_mm=25.4,
        force=True,
    )
    after = [wire.model_dump() for wire in session.require_schematic().wires]

    assert moved["rerouted_nets"] == ["A"]
    assert before != after
    assert {wire.net for wire in session.require_schematic().wires} == {"A"}


def test_connect_incremental_reroutes_only_changed_net(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 120, 80)
    component_add(session, "R1", "Device:R")
    component_add(session, "C1", "Device:C")
    component_add(session, "R2", "Device:R")
    component_place_relative(session, "C1", "R1", "right", 25.4)
    component_place_relative(session, "R2", "C1", "below", 25.4)

    create_net(session, "A")
    create_net(session, "B")
    connect_incremental(session, "A", ["R1.2", "C1.1"])
    sch = session.require_schematic()
    a_before = [wire.model_dump() for wire in sch.wires if wire.net == "A"]
    assert a_before

    connect_incremental(session, "B", ["C1.2", "R2.1"])

    assert [wire.model_dump() for wire in sch.wires if wire.net == "A"] == a_before
    assert any(wire.net == "B" for wire in sch.wires)
    assert {label.net for label in sch.labels} == {"A", "B"}


def test_incremental_router_avoids_divider_foreign_net_overlap():
    """Regression for the first pseudo-live divider generated through MCP."""
    vin_wires, _, _ = incremental._route_incremental_geometry(
        "VIN",
        [(20.32, 25.4), (63.5, 21.59)],
        [],
    )
    vout_wires, _, _ = incremental._route_incremental_geometry(
        "VOUT",
        [(63.5, 29.21), (63.5, 46.99), (96.52, 25.4)],
        vin_wires,
    )
    gnd_wires, _, _ = incremental._route_incremental_geometry(
        "GND",
        [(20.32, 27.94), (63.5, 54.61)],
        vin_wires + vout_wires,
    )

    groups = [vin_wires, vout_wires, gnd_wires]
    for index, left_group in enumerate(groups):
        for right_group in groups[index + 1 :]:
            assert not any(
                incremental._foreign_wire_contact_is_blocking(left, right)
                for left in left_group
                for right in right_group
            )

    # The previous router selected x=63.5 as the VIN/VOUT trunk and ran both
    # nets through the resistor body/centre. The pin keepout must still prevent it.
    assert not any(
        wire.x1 == wire.x2 == 63.5 and min(wire.y1, wire.y2) <= 25.4 <= max(wire.y1, wire.y2)
        for wire in vin_wires
    )


def test_semantic_validation_allows_clean_foreign_net_wire_crossing():
    schematic = Schematic(name="crossing")
    schematic.wires = [
        Wire(x1=10.0, y1=10.0, x2=30.0, y2=10.0, net="VIN"),
        Wire(x1=20.0, y1=5.0, x2=20.0, y2=15.0, net="VOUT"),
    ]

    violations = incremental._incremental_semantic_violations(
        circuit=incremental.Circuit(name="crossing"),
        schematic=schematic,
    )

    assert not any(item["type"] == "FOREIGN_NET_GEOMETRY_INTERSECTION" for item in violations)


def test_semantic_validation_blocks_foreign_net_endpoint_contact():
    schematic = Schematic(name="collision")
    schematic.wires = [
        Wire(x1=10.0, y1=10.0, x2=20.0, y2=10.0, net="VIN"),
        Wire(x1=20.0, y1=5.0, x2=20.0, y2=15.0, net="VOUT"),
    ]

    violations = incremental._incremental_semantic_violations(
        circuit=incremental.Circuit(name="collision"),
        schematic=schematic,
    )

    assert any(item["type"] == "FOREIGN_NET_GEOMETRY_INTERSECTION" for item in violations)


def test_checkpoint_blocks_semantic_net_that_was_not_incrementally_routed(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R")
    component_add(session, "C1", "Device:C")
    create_net(session, "SENSE")
    connect_pins(session, "SENSE", ["R1.2", "C1.1"])

    result = schematic_checkpoint(session, run_external=False)

    assert result["committed"] is False
    assert result["validation"]["blocking"] is True
    assert result["validation"]["semantic_violations"][0]["type"] == "NET_NOT_INCREMENTALLY_ROUTED"


def test_progressive_checkpoint_ignores_expected_incomplete_erc(tmp_path: Path, monkeypatch):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R")

    def fake_erc(*_args, **_kwargs):
        return {
            "available": True,
            "blocking": True,
            "violations": [
                {"severity": "error", "description": "Pin not connected"},
                {"severity": "error", "description": "Power input pin is not driven"},
            ],
        }

    monkeypatch.setattr(incremental._core, "run_kicad_erc", fake_erc)
    result = schematic_checkpoint(session, allow_incomplete=True)

    assert result["committed"] is True
    assert result["validation"]["blocking"] is False
    violations = result["validation"]["kicad"]["violations"]
    assert all(item["progressive_ignored"] is True for item in violations)


def test_progressive_checkpoint_keeps_real_erc_error_blocking(tmp_path: Path, monkeypatch):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R")

    def fake_erc(*_args, **_kwargs):
        return {
            "available": True,
            "blocking": True,
            "violations": [
                {
                    "severity": "error",
                    "description": "Power output connected to another power output",
                }
            ],
        }

    monkeypatch.setattr(incremental._core, "run_kicad_erc", fake_erc)
    result = schematic_checkpoint(session, allow_incomplete=True)

    assert result["committed"] is False
    assert result["validation"]["blocking"] is True
    assert "progressive_ignored" not in result["validation"]["kicad"]["violations"][0]


def test_checkpoint_and_export_current_without_global_compose(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R")
    component_add(session, "C1", "Device:C")
    component_place_relative(session, "C1", "R1", "right", 25.4)
    create_net(session, "SENSE")
    connect_incremental(session, "SENSE", ["R1.2", "C1.1"])

    checkpoint = schematic_checkpoint(session, run_external=False)
    assert checkpoint["committed"] is True
    assert checkpoint["semantic_dirty"] is False

    output = tmp_path / "incremental.kicad_sch"
    exported = schematic_export_current(
        session,
        str(output),
        run_external=False,
    )
    assert exported["ok"] is True
    assert exported["validated"] is True
    assert output.exists()
    assert "SENSE" in output.read_text(encoding="utf-8")

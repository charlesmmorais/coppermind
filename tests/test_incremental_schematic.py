from __future__ import annotations

from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.session import Session
from coppermind.tools.circuit import (
    component_add,
    connect_incremental,
    connect_pins,
    create_net,
    place_relative,
    schematic_checkpoint,
    schematic_export_current,
)
from coppermind.tools.core import project_create


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


def test_place_relative_moves_only_target_and_locks_it(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "C1", "Device:C", value="100n")

    sch = session.require_schematic()
    r1 = next(item for item in sch.symbols if item.reference == "R1")
    c1 = next(item for item in sch.symbols if item.reference == "C1")
    r1_before = (r1.x, r1.y)

    result = place_relative(session, "C1", "R1", direction="right", gap_mm=25.4)

    assert result["locked"] is True
    assert (r1.x, r1.y) == r1_before
    assert c1.x == r1.x + 25.4
    assert c1.y == r1.y
    assert session.require_circuit().components["C1"].properties["placement_locked"] == "true"


def test_connect_incremental_reroutes_only_changed_net(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 120, 80)
    component_add(session, "R1", "Device:R")
    component_add(session, "C1", "Device:C")
    component_add(session, "R2", "Device:R")
    place_relative(session, "C1", "R1", "right", 25.4)
    place_relative(session, "R2", "C1", "below", 25.4)

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


def test_checkpoint_and_export_current_without_global_compose(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "incremental", 100, 80)
    component_add(session, "R1", "Device:R")
    component_add(session, "C1", "Device:C")
    place_relative(session, "C1", "R1", "right", 25.4)
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

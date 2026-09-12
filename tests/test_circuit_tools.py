from __future__ import annotations

from pathlib import Path

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.session import Session
from coppermind.tools.circuit import (
    component_add,
    connect_pins,
    create_net,
    find_symbol,
    inspect_component,
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


def test_project_create_initializes_semantic_authoring_state(tmp_path: Path):
    session = _session(tmp_path)
    result = project_create(session, "demo", 100, 80)

    assert result["circuit_ir"] is True
    assert session.require_circuit().name == "demo"
    assert session.require_schematic().name == "demo"


def test_find_add_connect_and_inspect_without_coordinates(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "demo", 100, 80)

    found = find_symbol(session, "R", library="Device")
    assert found["matches"][0]["lib_id"] == "Device:R"
    assert found["matches"][0]["pin_count"] == 2

    added_r = component_add(session, "R1", "Device:R", value="10k")
    added_c = component_add(session, "C1", "Device:C", value="100nF")
    assert {p["number"] for p in added_r["pins"]} == {"1", "2"}
    assert {p["number"] for p in added_c["pins"]} == {"1", "2"}

    create_net(session, "SENSE")
    connected = connect_pins(session, "SENSE", ["R1.2", "C1.1"])
    assert connected["pins"] == ["R1.2", "C1.1"]

    inspected = inspect_component(session, "R1")
    pin2 = next(pin for pin in inspected["pins"] if pin["number"] == "2")
    assert pin2["nets"] == ["SENSE"]

    # The drawable schematic is populated internally; the agent supplied no x/y.
    sch = session.require_schematic()
    assert [symbol.reference for symbol in sch.symbols] == ["R1", "C1"]
    assert "Device:R" in sch.library_symbols
    assert sch.wires == []


def test_connect_rejects_pin_already_owned_by_another_net(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "demo", 100, 80)
    component_add(session, "R1", "Device:R")
    component_add(session, "C1", "Device:C")
    create_net(session, "A")
    create_net(session, "B")
    connect_pins(session, "A", ["R1.1", "C1.1"])

    with pytest.raises(ValueError, match="already connected to net 'A'"):
        connect_pins(session, "B", ["R1.1", "C1.2"])


def test_component_add_fails_for_nonexistent_real_symbol(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "demo", 100, 80)

    with pytest.raises(LookupError):
        component_add(session, "X1", "Device:DoesNotExist")

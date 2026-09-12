"""Schematic serializer uses real KiCad library definitions; no symbol fallback."""

from pathlib import Path

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolutionError, SymbolResolver
from coppermind.schematic.models import NetLabel, Schematic, SchSymbol, Wire
from coppermind.schematic.symbols import lib_symbol_def, pin_numbers
from coppermind.serialize import schematic_to_kicad_sch
from coppermind.session import Session
from coppermind.tools.routed import (
    label_add,
    schematic_create,
    schematic_export_sch,
    schematic_info,
    symbol_add,
    wire_add,
)

DEVICE_LIB = r'''(kicad_symbol_lib (version 20231120) (generator kicad_symbol_editor)
  (symbol "R"
    (pin_numbers (hide yes))
    (pin_names (offset 0))
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
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
  (symbol "R_Small"
    (extends "R")
    (property "Reference" "R" (at 0.762 0.508 90) (effects (font (size 1.27 1.27))))
    (property "Value" "R_Small" (at 1.524 -0.508 90) (effects (font (size 1.27 1.27))))
  )
)'''


def _balanced(text: str) -> bool:
    return text.count("(") == text.count(")")


def _resolver(tmp_path: Path) -> SymbolResolver:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    return SymbolResolver(search_paths=[tmp_path])


def test_lib_symbol_def_is_real_and_unknown_is_rejected(tmp_path):
    resolver = _resolver(tmp_path)
    definition = lib_symbol_def("Device:R", resolver)
    assert _balanced(definition)
    assert definition.startswith('(symbol "Device:R"')
    assert "(rectangle (start -1.016 -2.54)" in definition
    assert pin_numbers("Device:R", resolver) == ["1", "2"]
    with pytest.raises(SymbolResolutionError):
        pin_numbers("MCU:ESP32", resolver)


def test_serializer_structure_with_real_library_symbols(tmp_path):
    resolver = _resolver(tmp_path)
    schematic = Schematic(name="Demo")
    schematic.symbols.append(
        SchSymbol(lib_id="Device:R", reference="R1", value="330", x=100, y=80)
    )
    schematic.symbols.append(
        SchSymbol(lib_id="Device:R_Small", reference="R2", value="1k", x=120, y=80)
    )
    schematic.wires.append(Wire(x1=105.08, y1=80, x2=114.92, y2=80))
    schematic.labels.append(NetLabel(text="SIG", x=110, y=78))
    text = schematic_to_kicad_sch(schematic, resolver=resolver)

    assert _balanced(text)
    assert text.startswith("(kicad_sch")
    assert "(lib_symbols" in text
    assert '(symbol "Device:R"' in text
    assert '(symbol "Device:R_Small"' in text
    assert '(extends "Device:R")' in text
    assert '(lib_id "Device:R")' in text
    assert "(wire (pts" in text
    assert '(label "SIG"' in text
    assert "(sheet_instances" in text


def test_only_used_symbols_are_embedded(tmp_path):
    resolver = _resolver(tmp_path)
    schematic = Schematic(name="One")
    schematic.symbols.append(SchSymbol(lib_id="Device:R", reference="R1", x=0, y=0))
    text = schematic_to_kicad_sch(schematic, resolver=resolver)
    assert '(symbol "Device:R"' in text
    assert '(symbol "Device:R_Small"' not in text


def test_tools_build_and_export_from_configured_library(tmp_path, monkeypatch):
    _resolver(tmp_path)
    monkeypatch.setenv("COPPERMIND_KICAD_SYMBOL_DIRS", str(tmp_path))
    session = Session(backend=MemoryBackend())
    assert schematic_create(session, "ResistorDemo")["ok"]
    symbol_add(session, "Device:R", "R1", 100, 80, value="330")
    symbol_add(session, "Device:R_Small", "R2", 120, 80, value="1k")
    wire_add(session, 105.08, 80, 114.92, 80)
    label_add(session, "SIG", 110, 78)
    info = schematic_info(session)
    assert info["symbols"] == ["R1", "R2"]
    assert info["labels"] == ["SIG"]

    out = tmp_path / "resistors.kicad_sch"
    result = schematic_export_sch(session, str(out))
    assert result["ok"]
    text = out.read_text(encoding="utf-8")
    assert _balanced(text)
    assert '(symbol "Device:R"' in text


def test_duplicate_reference_rejected(tmp_path, monkeypatch):
    _resolver(tmp_path)
    monkeypatch.setenv("COPPERMIND_KICAD_SYMBOL_DIRS", str(tmp_path))
    session = Session(backend=MemoryBackend())
    schematic_create(session, "X")
    symbol_add(session, "Device:R", "R1", 0, 0)
    with pytest.raises(ValueError):
        symbol_add(session, "Device:R", "R1", 1, 1)


def test_export_rejects_wrong_extension():
    session = Session(backend=MemoryBackend())
    schematic_create(session, "X")
    with pytest.raises(Exception):
        schematic_export_sch(session, "/tmp/bad.kicad_pcb")


def test_junctions_serialized(tmp_path):
    from coppermind.schematic.models import Junction

    resolver = _resolver(tmp_path)
    schematic = Schematic(name="J")
    schematic.symbols.append(SchSymbol(lib_id="Device:R", reference="R1", x=0, y=0))
    schematic.junctions.append(Junction(x=10, y=20))
    text = schematic_to_kicad_sch(schematic, resolver=resolver)
    assert _balanced(text)
    assert "(junction (at 10 20)" in text

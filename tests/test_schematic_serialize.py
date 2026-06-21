"""MVP schematic: serializer + tools produce a valid .kicad_sch."""

from coppermind.backends.memory_backend import MemoryBackend
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


def _balanced(text: str) -> bool:
    return text.count("(") == text.count(")")


def test_lib_symbol_def_is_balanced_and_named():
    d = lib_symbol_def("Device:R")
    assert _balanced(d)
    assert d.startswith('(symbol "Device:R"')
    assert pin_numbers("Device:R") == ["1", "2"]
    # unknown lib_id falls back to a generic 2-pin symbol
    assert pin_numbers("MCU:ESP32") == ["1", "2"]


def test_serializer_structure():
    s = Schematic(name="Demo")
    s.symbols.append(SchSymbol(lib_id="Device:R", reference="R1", value="330", x=100, y=80))
    s.symbols.append(SchSymbol(lib_id="Device:LED", reference="D1", value="LED", x=120, y=80))
    s.wires.append(Wire(x1=105.08, y1=80, x2=114.92, y2=80))
    s.labels.append(NetLabel(text="LED1", x=110, y=78))
    t = schematic_to_kicad_sch(s)
    assert _balanced(t)
    assert t.startswith("(kicad_sch")
    assert "(lib_symbols" in t
    assert t.count("(lib_id") == 2          # two symbol instances
    assert '(lib_id "Device:R")' in t
    assert "(wire (pts" in t
    assert '(label "LED1"' in t
    assert '(sheet_instances' in t


def test_only_used_symbols_are_embedded():
    s = Schematic(name="One")
    s.symbols.append(SchSymbol(lib_id="Device:C", reference="C1", x=0, y=0))
    t = schematic_to_kicad_sch(s)
    assert '(symbol "Device:C"' in t
    assert '(symbol "Device:R"' not in t


def test_tools_build_and_export(tmp_path):
    s = Session(backend=MemoryBackend())
    assert schematic_create(s, "LEDSchematic")["ok"]
    symbol_add(s, "Device:R", "R1", 100, 80, value="330")
    symbol_add(s, "Device:LED", "D1", 120, 80, value="LED")
    wire_add(s, 105.08, 80, 114.92, 80)
    label_add(s, "LED1", 110, 78)
    info = schematic_info(s)
    assert info["symbols"] == ["R1", "D1"]
    assert info["labels"] == ["LED1"]

    out = tmp_path / "led.kicad_sch"
    res = schematic_export_sch(s, str(out))
    assert res["ok"]
    text = out.read_text(encoding="utf-8")
    assert _balanced(text)
    assert text.startswith("(kicad_sch")


def test_duplicate_reference_rejected():
    s = Session(backend=MemoryBackend())
    schematic_create(s, "X")
    symbol_add(s, "Device:R", "R1", 0, 0)
    try:
        symbol_add(s, "Device:R", "R1", 1, 1)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_export_rejects_wrong_extension():
    s = Session(backend=MemoryBackend())
    schematic_create(s, "X")
    try:
        schematic_export_sch(s, "/tmp/bad.kicad_pcb")
        assert False, "expected rejection"
    except Exception:
        pass

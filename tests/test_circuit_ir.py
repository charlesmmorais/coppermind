from pathlib import Path

import pytest

from coppermind.circuit import Circuit, Component, Constraint, PinRef
from coppermind.libraries import SymbolResolutionError, SymbolResolver


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


def resolver(tmp_path: Path) -> SymbolResolver:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    return SymbolResolver(search_paths=[tmp_path])


def test_resolver_reads_real_symbol_pins(tmp_path):
    result = resolver(tmp_path).resolve("Device:R")
    assert result.lib_id == "Device:R"
    assert [pin.number for pin in result.pins] == ["1", "2"]
    assert all(pin.electrical_type.value == "passive" for pin in result.pins)
    assert result.definitions[-1].raw_s_expression.startswith('(symbol "Device:R"')


def test_resolver_handles_symbol_inheritance(tmp_path):
    result = resolver(tmp_path).resolve("Device:R_Small")
    assert result.extends == "Device:R"
    assert [pin.number for pin in result.pins] == ["1", "2"]
    assert [definition.lib_id for definition in result.definitions] == [
        "Device:R",
        "Device:R_Small",
    ]
    assert '(extends "Device:R")' in result.definitions[-1].raw_s_expression


def test_unknown_symbol_is_hard_error_no_fallback(tmp_path):
    with pytest.raises(SymbolResolutionError):
        resolver(tmp_path).resolve("Device:DefinitelyMissing")


def test_circuit_ir_connects_by_component_and_pin_identity(tmp_path):
    symbol = resolver(tmp_path).resolve("Device:R")
    circuit = Circuit(name="demo")
    circuit.add_component(
        Component(
            reference="R1",
            symbol_id=symbol.lib_id,
            pins=symbol.pins_by_number(),
        )
    )
    circuit.add_component(
        Component(
            reference="R2",
            symbol_id=symbol.lib_id,
            pins=symbol.pins_by_number(),
        )
    )
    circuit.connect(
        "SIG",
        PinRef(component="R1", pin="2"),
        PinRef(component="R2", pin="1"),
    )
    circuit.constraints.append(
        Constraint(kind="near", targets=["R1", "R2"], parameters={"max_mm": 10})
    )

    assert circuit.validate_references() == []
    assert [node.key() for node in circuit.nets["SIG"].nodes] == ["R1.2", "R2.1"]

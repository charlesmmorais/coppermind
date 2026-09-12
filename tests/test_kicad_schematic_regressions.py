from pathlib import Path

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import compose_schematic
from coppermind.session import Session
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.composer import schematic_export_composed
from coppermind.tools.core import project_create


DEVICE_VERTICAL_LIB = r'''(kicad_symbol_lib
  (version 20231120)
  (generator kicad_symbol_editor)
  (symbol "R"
    (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27)
        (name "" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 1.27)
        (name "" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))))
)'''


POWER_LIB = r'''(kicad_symbol_lib
  (version 20231120)
  (generator kicad_symbol_editor)
  (symbol "PWR_FLAG"
    (property "Reference" "#FLG" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "PWR_FLAG" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "PWR_FLAG_0_1"
      (pin power_out line (at 0 0 0) (length 0)
        (name "pwr" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
)'''


def _session(tmp_path: Path) -> Session:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_VERTICAL_LIB, encoding="utf-8")
    (tmp_path / "power.kicad_sym").write_text(POWER_LIB, encoding="utf-8")
    session = Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )
    project_create(session, "regression", 100, 80)
    return session


def test_common_unit_zero_power_pin_is_available_to_unit_one(tmp_path: Path):
    session = _session(tmp_path)

    added = component_add(session, "#FLG01", "power:PWR_FLAG")

    assert added["unit"] == 1
    assert added["pins"][0]["number"] == "1"
    assert added["pins"][0]["unit"] == 0
    symbol = session.require_schematic().symbols[0]
    assert symbol.unit == 1
    library = session.require_schematic().library_symbols["power:PWR_FLAG"]
    assert library.pins_for_unit(1)[0].unit == 0


def test_vertical_half_grid_pin_anchors_are_not_snapped(tmp_path: Path):
    session = _session(tmp_path)
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "R2", "Device:R", value="10k")
    create_net(session, "VOUT")
    connect_pins(session, "VOUT", ["R1.2", "R2.1"])

    report = compose_schematic(session.require_circuit(), session.require_schematic())
    assert report.ok

    symbols = {item.reference: item for item in session.require_schematic().symbols}
    expected = {
        (symbols["R1"].x, symbols["R1"].y + 3.81),
        (symbols["R2"].x, symbols["R2"].y - 3.81),
    }
    actual = {
        (wire.x1, wire.y1)
        for wire in session.require_schematic().wires
    } | {
        (wire.x2, wire.y2)
        for wire in session.require_schematic().wires
    }

    for point in expected:
        assert any(
            x == pytest.approx(point[0]) and y == pytest.approx(point[1])
            for x, y in actual
        )

    # The real connection points are on 1.27/3.81 mm offsets, not 2.54 mm grid.
    assert any(not float(y / 2.54).is_integer() for _, y in expected)


def test_export_blocks_validation_failure_unless_explicitly_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    session = _session(tmp_path)
    component_add(session, "R1", "Device:R")
    output = tmp_path / "blocked.kicad_sch"

    blocked_pipeline = {
        "composition": {
            "ok": True,
            "components": 1,
            "nets": 0,
            "wires": 0,
            "labels": 0,
            "junctions": 0,
            "unresolved_pins": [],
        },
        "autofix": [],
        "semantic_violations": [],
        "kicad": {
            "available": True,
            "blocking": True,
            "violations": [{"severity": "error", "description": "synthetic regression"}],
        },
        "blocking": True,
    }
    monkeypatch.setattr(
        "coppermind.tools.composer.evaluate_schematic",
        lambda *args, **kwargs: blocked_pipeline,
    )

    result = schematic_export_composed(session, str(output))
    assert result["ok"] is False
    assert result["blocked"] is True
    assert not output.exists()

    forced = schematic_export_composed(session, str(output), allow_invalid=True)
    assert forced["ok"] is True
    assert forced["validated"] is False
    assert output.exists()

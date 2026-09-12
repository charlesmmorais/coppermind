from pathlib import Path

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import _pin_anchor, compose_schematic
from coppermind.schematic.visual_review import review_schematic_visual
from coppermind.session import Session
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import project_create


DEVICE_LIB = r'''(kicad_symbol_lib
  (version 20231120)
  (generator kicad_symbol_editor)
  (symbol "R"
    (property "Reference" "R" (at 2.54 0 90) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
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
  (symbol "+5V"
    (property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
    (property "Value" "+5V" (at 0 3.556 0) (effects (font (size 1.27 1.27))))
    (symbol "+5V_1_1"
      (pin power_in line (at 0 0 90) (length 0)
        (name "" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "GND"
    (property "Reference" "#PWR" (at 0 6.35 0) (effects (font (size 1.27 1.27))))
    (property "Value" "GND" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
    (symbol "GND_1_1"
      (pin power_in line (at 0 0 270) (length 0)
        (name "" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "PWR_FLAG"
    (property "Reference" "#FLG" (at 0 -1.905 0) (effects (font (size 1.27 1.27))))
    (property "Value" "PWR_FLAG" (at 0 1.905 0) (effects (font (size 1.27 1.27))))
    (symbol "PWR_FLAG_0_0"
      (pin power_out line (at 0 0 90) (length 0)
        (name "pwr" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))))
)'''


def _session(tmp_path: Path) -> Session:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    (tmp_path / "power.kicad_sym").write_text(POWER_LIB, encoding="utf-8")
    session = Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )
    project_create(session, "power_layout", 100, 80)
    return session


def _divider(tmp_path: Path) -> Session:
    session = _session(tmp_path)
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "R2", "Device:R", value="10k")
    component_add(session, "#PWR01", "power:+5V", value="+5V")
    component_add(session, "#PWR02", "power:GND", value="GND")
    component_add(session, "#FLG01", "power:PWR_FLAG", value="PWR_FLAG")
    component_add(session, "#FLG02", "power:PWR_FLAG", value="PWR_FLAG")

    create_net(session, "+5V")
    create_net(session, "VOUT")
    create_net(session, "GND")
    connect_pins(session, "+5V", ["#PWR01.1", "#FLG01.1", "R1.1"])
    connect_pins(session, "VOUT", ["R1.2", "R2.1"])
    connect_pins(session, "GND", ["R2.2", "#PWR02.1", "#FLG02.1"])
    return session


def test_power_bounded_passive_chain_is_compact_and_vertical(tmp_path: Path):
    session = _divider(tmp_path)
    report = compose_schematic(session.require_circuit(), session.require_schematic())
    assert report.ok

    schematic = session.require_schematic()
    symbols = {symbol.reference: symbol for symbol in schematic.symbols}

    assert symbols["R1"].x == pytest.approx(symbols["R2"].x)
    assert symbols["R1"].y < symbols["R2"].y

    top = _pin_anchor(schematic, "R1", "1")
    bottom = _pin_anchor(schematic, "R2", "2")
    supply = _pin_anchor(schematic, "#PWR01", "1")
    ground = _pin_anchor(schematic, "#PWR02", "1")
    assert top is not None and bottom is not None
    assert supply is not None and ground is not None

    # Named rail glyphs are separated from the functional symbol and joined by
    # a short vertical wire, avoiding an intentional visual overlap.
    assert supply[0] == pytest.approx(top[0])
    assert supply[1] == pytest.approx(top[1] - 15.24)
    assert ground[0] == pytest.approx(bottom[0])
    assert ground[1] == pytest.approx(bottom[1] + 15.24)

    top_flag = _pin_anchor(schematic, "#FLG01", "1")
    bottom_flag = _pin_anchor(schematic, "#FLG02", "1")
    assert top_flag is not None and bottom_flag is not None
    assert top_flag[1] == pytest.approx(top[1])
    assert bottom_flag[1] == pytest.approx(bottom[1])
    assert abs(top_flag[0] - top[0]) == pytest.approx(25.4)
    assert abs(bottom_flag[0] - bottom[0]) == pytest.approx(25.4)

    # The rail symbols already name +5V/GND; only the signal net needs a label.
    assert [label.text for label in schematic.labels] == ["VOUT"]
    vout = schematic.labels[0]
    r1_out = _pin_anchor(schematic, "R1", "2")
    r2_in = _pin_anchor(schematic, "R2", "1")
    assert r1_out is not None and r2_in is not None
    assert vout.x == pytest.approx(r1_out[0])
    assert min(r1_out[1], r2_in[1]) < vout.y < max(r1_out[1], r2_in[1])

    xs = [symbol.x for symbol in schematic.symbols]
    ys = [symbol.y for symbol in schematic.symbols]
    assert max(xs) - min(xs) <= 30.48
    assert max(ys) - min(ys) <= 66.04

    visual = review_schematic_visual(
        schematic,
        circuit=session.require_circuit(),
        run_render=False,
    )
    assert visual["score"] >= 85
    assert visual["blocking"] is False

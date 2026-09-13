from __future__ import annotations

from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.incremental import validate_incremental_schematic
from coppermind.session import Session
from coppermind.tools.auto_placement import component_place_auto
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import project_create


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


def _add(session: Session, reference: str, value: str = "10k") -> None:
    component_add(session, reference, "Device:R", value=value)


def _connect(session: Session, net: str, *pins: str) -> None:
    connect_pins(session, net, list(pins))


def _place(session: Session, reference: str, anchor: str) -> dict:
    result = component_place_auto(session, reference, anchor, gap_mm=25.4)
    assert result["ok"] is True
    assert result["chosen_mode"] in {"relative", "free-space"}
    if result["chosen_mode"] == "relative":
        assert result["chosen_direction"] in {"right", "below", "above", "left"}
        assert result["chosen_gap_mm"] in {20.32, 25.4, 38.1, 50.8}
    else:
        assert result["chosen_direction"] is None
        assert result["chosen_gap_mm"] is None
    assert any(candidate.get("ok") for candidate in result["candidates"])
    return result


def _all_geometry_points(session: Session) -> list[tuple[float, float]]:
    schematic = session.require_schematic()
    points = [(symbol.x, symbol.y) for symbol in schematic.symbols]
    for wire in schematic.wires:
        points.extend(((wire.x1, wire.y1), (wire.x2, wire.y2)))
    points.extend((label.x, label.y) for label in schematic.labels)
    points.extend((junction.x, junction.y) for junction in schematic.junctions)
    return points


def test_dense_semantic_first_auto_placement_routes_every_net(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "dense_auto", 180, 110)
    for net in ("VIN", "VOUT", "FB", "SENSE", "GND"):
        create_net(session, net)

    _add(session, "R1", "10k")

    _add(session, "R2", "20k")
    _connect(session, "VOUT", "R1.2", "R2.1")
    _place(session, "R2", "R1")

    _add(session, "R3", "47k")
    _connect(session, "VOUT", "R1.2", "R3.1")
    _connect(session, "GND", "R2.2", "R3.2")
    _place(session, "R3", "R2")

    _add(session, "R4", "100k")
    _connect(session, "VOUT", "R1.2", "R4.1")
    _place(session, "R4", "R1")

    _add(session, "R5", "10k")
    _connect(session, "FB", "R4.2", "R5.1")
    _connect(session, "GND", "R2.2", "R5.2")
    _place(session, "R5", "R4")

    _add(session, "R6", "10k")
    _connect(session, "FB", "R4.2", "R6.1")
    _connect(session, "GND", "R2.2", "R6.2")
    _place(session, "R6", "R5")

    _add(session, "R7", "4.7k")
    _connect(session, "VOUT", "R1.2", "R7.1")
    _place(session, "R7", "R4")

    _add(session, "R8", "1k")
    _connect(session, "SENSE", "R7.2", "R8.1")
    _connect(session, "GND", "R2.2", "R8.2")
    _place(session, "R8", "R7")

    _add(session, "R9", "100k")
    _connect(session, "VIN", "R1.1", "R9.1")
    _connect(session, "SENSE", "R7.2", "R9.2")
    r9 = _place(session, "R9", "R7")

    validation = validate_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=False,
    )

    assert validation["semantic_violations"] == []
    assert validation["blocking"] is False
    assert set(r9["rerouted_nets"]) == {"SENSE", "VIN"}

    routed = {wire.net for wire in session.require_schematic().wires if wire.net}
    assert {"VIN", "VOUT", "FB", "SENSE", "GND"}.issubset(routed)

    positions = {
        (symbol.x, symbol.y)
        for symbol in session.require_schematic().symbols
        if symbol.reference.startswith("R")
    }
    assert len(positions) == 9

    # A4 is serialized landscape (297 x 210 mm). Keep all incremental geometry
    # inside the same 12.7 mm safe margin enforced by the auto placer.
    points = _all_geometry_points(session)
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert min(xs) >= 12.7 - 1e-6
    assert min(ys) >= 12.7 - 1e-6
    assert max(xs) <= 297.0 - 12.7 + 1e-6
    assert max(ys) <= 210.0 - 12.7 + 1e-6

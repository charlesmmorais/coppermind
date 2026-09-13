from __future__ import annotations

from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.incremental import validate_incremental_schematic
from coppermind.session import Session
from coppermind.tools.circuit import (
    component_add,
    component_place_relative,
    connect_incremental,
    create_net,
    schematic_checkpoint,
)
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
        (number "2" (effects (font (size 1.27 1.27)))))))
)'''


def _session(tmp_path: Path) -> Session:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    return Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )


def _add(session: Session, reference: str, value: str = "10k") -> None:
    component_add(session, reference, "Device:R", value=value)


def _place(
    session: Session,
    reference: str,
    anchor: str,
    direction: str,
    gap_mm: float = 25.4,
) -> None:
    component_place_relative(
        session,
        reference,
        anchor,
        direction=direction,
        gap_mm=gap_mm,
    )


def _connect(session: Session, net: str, *pins: str) -> None:
    connect_incremental(session, net, list(pins))


def _net_geometry(session: Session, net: str) -> list[dict]:
    return [
        wire.model_dump()
        for wire in session.require_schematic().wires
        if wire.net == net
    ]


def test_dense_incremental_build_preserves_unrelated_nets(tmp_path: Path):
    session = _session(tmp_path)
    project_create(session, "dense_incremental", 180, 110)
    for net in ("VIN", "VOUT", "FB", "SENSE", "GND"):
        create_net(session, net)

    _add(session, "R1", "10k")
    _add(session, "R2", "20k")
    _place(session, "R2", "R1", "below")
    _connect(session, "VOUT", "R1.2", "R2.1")

    _add(session, "R3", "47k")
    _place(session, "R3", "R2", "right")
    _connect(session, "VOUT", "R1.2", "R3.1")
    _connect(session, "GND", "R2.2", "R3.2")

    _add(session, "R4", "100k")
    _place(session, "R4", "R1", "right", 38.1)
    _add(session, "R5", "10k")
    _place(session, "R5", "R4", "below")
    _connect(session, "VOUT", "R1.2", "R4.1")
    _connect(session, "FB", "R4.2", "R5.1")
    _connect(session, "GND", "R2.2", "R5.2")

    _add(session, "R6", "10k")
    _place(session, "R6", "R5", "right")
    _connect(session, "FB", "R4.2", "R6.1")
    _connect(session, "GND", "R2.2", "R6.2")

    fb_before_sense = _net_geometry(session, "FB")
    assert fb_before_sense

    _add(session, "R7", "4.7k")
    _place(session, "R7", "R4", "right", 38.1)
    _add(session, "R8", "1k")
    _place(session, "R8", "R7", "below")
    _connect(session, "VOUT", "R1.2", "R7.1")
    _connect(session, "SENSE", "R7.2", "R8.1")
    _connect(session, "GND", "R2.2", "R8.2")

    assert _net_geometry(session, "FB") == fb_before_sense
    settled_before_r9 = {
        name: _net_geometry(session, name)
        for name in ("VOUT", "FB", "GND")
    }

    _add(session, "R9", "100k")
    _place(session, "R9", "R7", "right", 38.1)
    _connect(session, "VIN", "R1.1", "R9.1")
    _connect(session, "SENSE", "R7.2", "R9.2")

    for name, geometry in settled_before_r9.items():
        assert _net_geometry(session, name) == geometry

    validation = validate_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=False,
    )
    assert validation["blocking"] is False
    assert validation["semantic_violations"] == []
    assert {wire.net for wire in session.require_schematic().wires} == {
        "VIN",
        "VOUT",
        "FB",
        "SENSE",
        "GND",
    }

    checkpoint = schematic_checkpoint(session, run_external=False)
    assert checkpoint["committed"] is True

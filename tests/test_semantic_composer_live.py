import json
import shutil

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.schematic.visual_review import evaluate_visual_schematic
from coppermind.session import Session
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import project_create


@pytest.mark.integration
def test_composed_divider_is_electrically_connected_in_real_kicad():
    if shutil.which("kicad-cli") is None:
        pytest.skip("kicad-cli is not installed")

    session = Session(backend=MemoryBackend())
    project_create(session, "erc_live", 100, 80)
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

    result = evaluate_visual_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=True,
    )

    assert result["composition"]["ok"] is True, result
    assert result["kicad"]["available"] is True, result
    errors = [
        item
        for item in result["kicad"]["violations"]
        if item.get("severity") in {"error", "fatal"}
    ]
    if errors:
        schematic = session.require_schematic()
        diagnostics = {
            "errors": [
                {
                    "description": item.get("description"),
                    "type": item.get("raw", {}).get("type"),
                    "items": item.get("raw", {}).get("items", []),
                }
                for item in errors
            ],
            "symbols": [
                {
                    "reference": symbol.reference,
                    "lib_id": symbol.lib_id,
                    "unit": symbol.unit,
                    "at": [symbol.x, symbol.y, symbol.rotation],
                }
                for symbol in schematic.symbols
            ],
            "wires": [
                [[wire.x1, wire.y1], [wire.x2, wire.y2]]
                for wire in schematic.wires
            ],
            "labels": [
                [label.text, label.x, label.y]
                for label in schematic.labels
            ],
        }
        pytest.fail(json.dumps(diagnostics, indent=2, sort_keys=True))
    assert result["kicad"]["blocking"] is False, result
    assert result["blocking"] is False, result

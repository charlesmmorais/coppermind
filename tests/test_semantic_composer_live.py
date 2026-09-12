import shutil

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.schematic.composer import compose_schematic
from coppermind.schematic.erc import run_kicad_erc
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import project_create


@pytest.mark.integration
def test_composed_schematic_is_accepted_by_real_kicad_erc():
    if shutil.which("kicad-cli") is None:
        pytest.skip("kicad-cli is not installed")

    session = Session(backend=MemoryBackend())
    project_create(session, "erc_live", 100, 80)
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "C1", "Device:C", value="100n")
    create_net(session, "SENSE")
    connect_pins(session, "SENSE", ["R1.2", "C1.1"])

    composition = compose_schematic(session.require_circuit(), session.require_schematic())
    assert composition.ok

    result = run_kicad_erc(session.require_schematic(), resolver=session.symbol_resolver)
    assert result["available"] is True
    assert result.get("returncode") in (0, 5), result
    assert "error" not in result, result

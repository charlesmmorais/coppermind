import shutil

import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.schematic.visual_review import evaluate_visual_schematic
from coppermind.session import Session
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import project_create


@pytest.mark.integration
def test_visual_pipeline_renders_real_kicad_svg_and_reruns_erc():
    if shutil.which("kicad-cli") is None:
        pytest.skip("kicad-cli is not installed")

    session = Session(backend=MemoryBackend())
    project_create(session, "visual_live", 100, 80)
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "C1", "Device:C", value="100n")
    create_net(session, "SENSE")
    connect_pins(session, "SENSE", ["R1.2", "C1.1"])

    result = evaluate_visual_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        include_svg=True,
    )

    visual = result["visual_review"]["review"]
    assert visual["render"]["available"] is True, visual
    assert visual["render"]["page_count"] >= 1
    assert "<svg" in visual["render"]["pages"][0]["svg"]
    assert result["kicad"]["available"] is True
    assert result["kicad"].get("returncode") in (0, 5), result
    assert "error" not in result["kicad"], result

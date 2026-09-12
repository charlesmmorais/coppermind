from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import compose_schematic
from coppermind.schematic.visual_review import (
    optimize_visual_layout,
    render_schematic_svg,
    review_schematic_visual,
)
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import design_preview, project_create


WIDE_LIB = r'''(kicad_symbol_lib
  (version 20231120)
  (generator kicad_symbol_editor)
  (symbol "W"
    (property "Reference" "R" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "W" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "W_1_1"
      (pin passive line (at -25.4 0 0) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 25.4 0 180) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))))
)'''


def _wide_pair(tmp_path: Path) -> Session:
    (tmp_path / "Wide.kicad_sym").write_text(WIDE_LIB, encoding="utf-8")
    session = Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )
    project_create(session, "visual", 100, 80)
    component_add(session, "R1", "Wide:W", value="A")
    component_add(session, "R2", "Wide:W", value="B")
    create_net(session, "SIGNAL")
    connect_pins(session, "SIGNAL", ["R1.2", "R2.1"])
    compose_schematic(session.require_circuit(), session.require_schematic())
    return session


def test_visual_review_detects_overlapping_symbol_bounds(tmp_path: Path):
    session = _wide_pair(tmp_path)
    review = review_schematic_visual(
        session.require_schematic(),
        circuit=session.require_circuit(),
        run_render=False,
    )
    assert review["metrics"]["symbol_overlaps"] >= 1
    assert any(item["code"] == "SYMBOL_OVERLAP" for item in review["findings"])
    assert review["score"] < 100


def test_visual_optimizer_increases_spacing_without_changing_circuit_ir(tmp_path: Path):
    session = _wide_pair(tmp_path)
    before = session.require_circuit().model_dump(mode="json")
    result = optimize_visual_layout(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        target_score=95,
        max_passes=3,
        run_render=False,
    )
    after = session.require_circuit().model_dump(mode="json")
    assert after == before
    assert result["review"]["metrics"]["symbol_overlaps"] == 0
    assert result["review"]["score"] >= 95
    assert result["selected_scale"]["x"] > 1.0


def test_missing_kicad_cli_is_nonfatal_for_offline_visual_review(tmp_path: Path):
    session = _wide_pair(tmp_path)
    result = render_schematic_svg(
        session.require_schematic(),
        resolver=session.symbol_resolver,
        executable="coppermind-kicad-cli-does-not-exist",
    )
    assert result["available"] is False
    assert result["pages"] == []


def test_design_preview_runs_visual_reviewer(tmp_path: Path):
    session = _wide_pair(tmp_path)
    preview = design_preview(session)
    assert preview["visual_review"] is not None
    assert preview["visual_review"]["review"]["score"] >= 0
    assert preview["schematic_pipeline"]["visual_review"] == preview["visual_review"]


def test_visual_tools_are_routed_and_discoverable():
    assert "schematic_visual_review" in REGISTRY.names
    assert "schematic_visual_optimize" in REGISTRY.names

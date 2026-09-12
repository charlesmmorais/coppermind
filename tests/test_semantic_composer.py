from pathlib import Path

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.circuit import PinRef
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import compose_schematic, symbol_pin_geometry
from coppermind.schematic.erc import evaluate_schematic
from coppermind.serialize.kicad_sch import schematic_to_kicad_sch
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.circuit import component_add, connect_pins, create_net
from coppermind.tools.core import design_preview, project_create


DEVICE_LIB = r'''(kicad_symbol_lib
  (version 20231120)
  (generator kicad_symbol_editor)
  (symbol "R"
    (property "Reference" "R" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_0_1"
      (rectangle (start -2.54 1.016) (end 2.54 -1.016)
        (stroke (width 0) (type default)) (fill (type none))))
    (symbol "R_1_1"
      (pin passive line (at -5.08 0 0) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 5.08 0 180) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "C"
    (property "Reference" "C" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "C_1_1"
      (pin passive line (at -2.54 0 0) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 2.54 0 180) (length 2.54)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))))
)'''


def _session(tmp_path: Path) -> Session:
    (tmp_path / "Device.kicad_sym").write_text(DEVICE_LIB, encoding="utf-8")
    session = Session(
        backend=MemoryBackend(),
        symbol_resolver=SymbolResolver(search_paths=[tmp_path]),
    )
    project_create(session, "semantic", 100, 80)
    return session


def _connected_pair(tmp_path: Path) -> Session:
    session = _session(tmp_path)
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "C1", "Device:C", value="100n")
    create_net(session, "SENSE")
    connect_pins(session, "SENSE", ["R1.2", "C1.1"])
    return session


def test_reads_real_pin_geometry_from_symbol_library(tmp_path: Path):
    session = _connected_pair(tmp_path)
    library = session.require_schematic().library_symbols["Device:R"]
    pins = symbol_pin_geometry(library, 1)
    assert pins["1"].x == -5.08
    assert pins["2"].x == 5.08
    assert pins["2"].rotation == 180


def test_circuit_ir_lowers_to_layout_wires_labels_and_real_kicad_sch(tmp_path: Path):
    session = _connected_pair(tmp_path)
    report = compose_schematic(session.require_circuit(), session.require_schematic())
    sch = session.require_schematic()

    assert report.ok
    assert report.components == 2
    assert report.nets == 1
    assert len(sch.wires) >= 1
    assert [label.text for label in sch.labels] == ["SENSE"]
    assert all((symbol.x, symbol.y) != (0, 0) for symbol in sch.symbols)

    text = schematic_to_kicad_sch(sch, session.symbol_resolver)
    assert '(label "SENSE"' in text
    assert "(wire (pts" in text
    assert '(lib_id "Device:R")' in text


def test_erc_pipeline_can_run_semantic_only_and_is_nonblocking(tmp_path: Path):
    session = _connected_pair(tmp_path)
    result = evaluate_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=False,
    )
    assert result["blocking"] is False
    assert result["composition"]["ok"] is True
    assert result["semantic_violations"] == []


def test_single_node_net_returns_feedback_without_blocking(tmp_path: Path):
    session = _session(tmp_path)
    component_add(session, "R1", "Device:R")
    create_net(session, "FLOATING")
    session.require_circuit().connect("FLOATING", PinRef(component="R1", pin="1"))
    result = evaluate_schematic(
        session.require_circuit(), session.require_schematic(), run_external=False
    )
    assert result["blocking"] is False
    assert result["semantic_violations"][0]["type"] == "SINGLE_NODE_NET"
    assert result["semantic_violations"][0]["feedback"]


def test_design_preview_automatically_runs_semantic_composer(tmp_path: Path):
    session = _connected_pair(tmp_path)
    preview = design_preview(session)
    assert preview["schematic_pipeline"]["composition"]["ok"] is True
    assert preview["schematic_pipeline"]["composition"]["wires"] >= 1


def test_composer_diagnostics_are_routed_not_always_visible():
    assert "schematic_compose" in REGISTRY.names
    assert "schematic_erc" in REGISTRY.names
    assert "schematic_export_composed" in REGISTRY.names
    assert "wire_add" not in REGISTRY.names
    assert "symbol_add" not in REGISTRY.names

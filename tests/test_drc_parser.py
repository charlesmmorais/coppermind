from coppermind.backends.drc import build_drc_command, parse_drc_report
from coppermind.verification.checks import Severity, has_blocking

SAMPLE = {
    "source": "board.kicad_pcb",
    "coordinate_units": "mm",
    "violations": [
        {
            "type": "clearance",
            "description": "Clearance violation (netclass 'Default')",
            "severity": "error",
            "excluded": False,
            "items": [{"uuid": "a", "description": "Track [GND]", "pos": {"x": 1.0, "y": 2.0}}],
        },
        {
            "type": "silk_edge_clearance",
            "description": "Silkscreen clipped by board edge",
            "severity": "warning",
            "excluded": False,
            "items": [],
        },
        {
            "type": "already_excluded",
            "description": "User excluded",
            "severity": "error",
            "excluded": True,
            "items": [],
        },
    ],
    "unconnected_items": [
        {
            "type": "unconnected",
            "description": "Missing connection: LED1",
            "severity": "error",
            "items": [{"uuid": "u", "description": "Pad", "pos": {"x": 3, "y": 4}}],
        }
    ],
    "schematic_parity": [],
}


def test_parse_merges_sections_and_skips_excluded():
    vs = parse_drc_report(SAMPLE)
    codes = {v.code for v in vs}
    assert "DRC:clearance" in codes
    assert "DRC:silk_edge_clearance" in codes
    assert "UNCONNECTED:unconnected" in codes
    assert "DRC:already_excluded" not in codes  # excluded skipped
    assert len(vs) == 3


def test_parse_maps_severity_and_blocks():
    vs = parse_drc_report(SAMPLE)
    assert has_blocking(vs)  # has error-level entries
    clearance = next(v for v in vs if v.code == "DRC:clearance")
    assert clearance.severity == Severity.ERROR
    assert clearance.where == "(1.0, 2.0)"
    assert "KiCAD DRC" in clearance.rule


def test_parse_can_include_excluded():
    vs = parse_drc_report(SAMPLE, include_excluded=True)
    assert any(v.code == "DRC:already_excluded" for v in vs)


def test_parse_empty_report():
    assert parse_drc_report({}) == []


def test_build_drc_command_shape():
    cmd = build_drc_command("/b.kicad_pcb", "/out.json", kicad_cli="kicad-cli")
    assert cmd[:3] == ["kicad-cli", "pcb", "drc"]
    assert "--format" in cmd and "json" in cmd
    assert "--severity-all" in cmd
    assert cmd[-1] == "/b.kicad_pcb"
    assert "/out.json" in cmd

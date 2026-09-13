"""Exercise the serialized circuit in real KiCad, including exact pin identity."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.schematic.composer import _child, _parse_sexpr
from coppermind.tools.circuit import (
    component_add,
    connect_incremental,
    create_net,
    schematic_export_current,
)
from coppermind.tools.core import project_create

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="requires real KiCad CLI"),
]


def _exported_pin_sets(path: Path) -> dict[str, set[tuple[str, str]]]:
    output = path.with_suffix(".net")
    subprocess.run(
        [
            "kicad-cli",
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "--output",
            str(output),
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    root = ET.parse(output).getroot()
    return {
        net.attrib["name"].lstrip("/"): {
            (node.attrib["ref"], node.attrib["pin"]) for node in net.findall("node")
        }
        for net in root.findall("./nets/net")
    }


def _assert_rendered_fields_are_horizontal(path: Path, expected: set[str]) -> None:
    output = path.parent / "svg"
    output.mkdir(exist_ok=True)
    subprocess.run(
        ["kicad-cli", "sch", "export", "svg", "--output", str(output) + os.sep, str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    found = set()

    def visit(node, transforms=""):
        transforms += " " + node.attrib.get("transform", "")
        if node.tag.endswith("}text"):
            value = "".join(node.itertext()).strip()
            if value in expected:
                found.add(value)
                angles = re.findall(r"rotate\(\s*([-+.0-9]+)", transforms)
                assert all(float(angle) % 360 == 0 for angle in angles), (value, transforms)
        for child in node:
            visit(child, transforms)

    for svg in output.glob("*.svg"):
        visit(ET.parse(svg).getroot())
    assert found == expected, f"missing rendered fields: {expected - found}"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_pin_identity_matches_real_kicad_netlist(tmp_path: Path, rotation: int):
    session = Session(backend=MemoryBackend())
    project_create(session, "rotation_identity", 160, 90)
    component_add(session, "J1", "Connector_Generic:Conn_01x01", value="INPUT")
    component_add(session, "R1", "Device:R", value="10k")
    component_add(session, "J2", "Connector_Generic:Conn_01x01", value="OUTPUT")
    target = next(s for s in session.require_schematic().symbols if s.reference == "R1")
    target.rotation = rotation
    create_net(session, "VIN")
    create_net(session, "VOUT")
    connect_incremental(session, "VIN", ["J1.1", "R1.1"])
    connect_incremental(session, "VOUT", ["R1.2", "J2.1"])

    output = tmp_path / "rotation_identity.kicad_sch"
    result = schematic_export_current(session, str(output))
    if result["validation"]["blocking"]:
        print(json.dumps(result, indent=2))
        print(session.require_schematic().model_dump_json(indent=2))
    assert result["validation"]["kicad"]["available"] is True, result
    assert result["validation"]["blocking"] is False, result
    assert result["validated"] is True, result
    # ERC alone may accept swapped passive pins. Compare the *actual* KiCad
    # netlist with Circuit IR, so all four rotations preserve net-to-pin identity.
    assert _exported_pin_sets(output) == {
        "VIN": {("J1", "1"), ("R1", "1")},
        "VOUT": {("R1", "2"), ("J2", "1")},
    }
    _assert_rendered_fields_are_horizontal(output, {"R1", "10k"})


def test_exact_mcp_flow_demo_passes_strict_erc_and_netlist(tmp_path: Path):
    example = Path(__file__).resolve().parents[1] / "examples" / "flow_orientation_mcp.py"
    spec = importlib.util.spec_from_file_location("flow_orientation_demo", example)
    assert spec is not None and spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    output = (
        Path(os.environ.get("COPPERMIND_VISUAL_ARTIFACTS", str(tmp_path)))
        / "flow_orientation_demo.kicad_sch"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    async def run():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "coppermind.server", "--transport", "stdio"],
            env={**os.environ, "COPPERMIND_BACKEND": "memory"},
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await demo.build_demo(session, output)

    result = asyncio.run(asyncio.wait_for(run(), timeout=180))
    assert result["validated"] is True, result
    assert result["validation"]["kicad"]["available"] is True, result
    assert result["validation"]["blocking"] is False, result
    assert _exported_pin_sets(output) == {
        "VIN": {("J1", "1"), ("R1", "1")},
        "N12": {("R1", "2"), ("R2", "1")},
        "N23": {("R2", "2"), ("R3", "1")},
        "VOUT": {("R3", "2"), ("J2", "1")},
    }
    # A green ERC is insufficient: prevent the accepted-but-visually-wrong
    # R1 -> R3 -> R2 ordering seen in the user's KiCad screenshot.
    root = _parse_sexpr(output.read_text())
    placements = {}
    for node in root:
        if isinstance(node, list) and node and node[0] == "symbol":
            fields = {p[1]: p[2] for p in node if isinstance(p, list) and p[0] == "property"}
            placements[fields["Reference"]] = [float(v) for v in _child(node, "at")[1:4]]
    assert placements["J1"][0] < placements["R1"][0] < placements["R2"][0]
    assert placements["R2"][0] < placements["R3"][0] < placements["J2"][0]
    assert {placements[r][1] for r in ("R1", "R2", "R3")} == {placements["R1"][1]}
    assert all(placements[r][2] == 90 for r in ("R1", "R2", "R3"))
    _assert_rendered_fields_are_horizontal(output, {"R1", "R2", "R3", "10k", "22k", "47k"})


def _assert_resistor_bodies_clear_of_wires(path: Path):
    # Independent bounds of the real rectangular Device:R body; no production
    # collision helper here, so deleting the router's obstacle check fails CI.
    root = _parse_sexpr(path.read_text())
    wires, bodies = [], []
    for node in root:
        if not isinstance(node, list) or not node:
            continue
        if node[0] == "wire":
            a, b = _child(node, "pts")[1:]
            wires.append(tuple(float(v) for v in (*a[1:], *b[1:])))
        if node[0] == "symbol" and _child(node, "lib_id")[1] == "Device:R":
            x, y, angle = map(float, _child(node, "at")[1:])
            dx, dy = (2.54, 1.016) if angle % 180 else (1.016, 2.54)
            bodies.append((x - dx, y - dy, x + dx, y + dy))
    assert bodies
    for left, top, right, bottom in bodies:
        for x1, y1, x2, y2 in wires:
            if y1 == y2:
                assert not (top <= y1 <= bottom and max(x1, x2) > left and min(x1, x2) < right), (
                    path,
                    (x1, y1, x2, y2),
                )
            else:
                assert not (left <= x1 <= right and max(y1, y2) > top and min(y1, y2) < bottom), (
                    path,
                    (x1, y1, x2, y2),
                )


def test_visual_divider_and_dense_mcp_cases(tmp_path: Path, monkeypatch):
    """Keep actual KiCad renderings and exact netlists of both review stages."""
    examples = Path(__file__).resolve().parents[1] / "examples"
    monkeypatch.syspath_prepend(str(examples))
    from flow_visual_validation_mcp import build_cases

    output = Path(os.environ.get("COPPERMIND_VISUAL_ARTIFACTS", str(tmp_path)))

    async def run():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "coppermind.server", "--transport", "stdio"],
            env={**os.environ, "COPPERMIND_BACKEND": "memory"},
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await build_cases(session, output)

    report = asyncio.run(asyncio.wait_for(run(), timeout=300))
    expected = {
        "divider": {
            "VIN": {("J1", "1"), ("R1", "1")},
            "VOUT": {("R1", "2"), ("R2", "1")},
            "GND": {("R2", "2"), ("J2", "1")},
        },
        "dense": {
            "VIN": {("R1", "1"), ("R9", "1")},
            "VOUT": {("R1", "2"), ("R2", "1"), ("R3", "1"), ("R4", "1"), ("R7", "1")},
            "FB": {("R4", "2"), ("R5", "1"), ("R6", "1")},
            "SENSE": {("R7", "2"), ("R8", "1"), ("R9", "2")},
            "GND": {("R2", "2"), ("R3", "2"), ("R5", "2"), ("R6", "2"), ("R8", "2")},
        },
    }
    for case in ("divider", "dense"):
        assert report[case]["validation"]["blocking"] is False
        assert report[case]["validation"]["visual_violations"] == []
        assert report[case]["validation"]["kicad"]["available"] is True
        for stage in ("before", "after"):
            path = output / f"{case}_{stage}.kicad_sch"
            assert _exported_pin_sets(path) == expected[case]
            _assert_resistor_bodies_clear_of_wires(path)
            references = set(report[case][stage]["symbols"])
            _assert_rendered_fields_are_horizontal(path, references)
    for result in report["divider"]["orientations"].values():
        assert {c["rotation"] for c in result["candidates"]} == {0, 90, 180, 270}
        assert result["display_axis"] == "vertical"
    assert {c["rotation"] for c in report["dense"]["orientation"]["candidates"]} == {
        0,
        90,
        180,
        270,
    }

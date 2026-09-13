"""Exercise the serialized circuit in real KiCad, including exact pin identity."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
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


def test_exact_mcp_flow_demo_passes_strict_erc_and_netlist(tmp_path: Path):
    example = Path(__file__).resolve().parents[1] / "examples" / "flow_orientation_mcp.py"
    spec = importlib.util.spec_from_file_location("flow_orientation_demo", example)
    assert spec is not None and spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    output = tmp_path / "flow_orientation_demo.kicad_sch"

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

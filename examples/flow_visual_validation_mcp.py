"""Export vertical-divider and dense before/after cases through semantic MCP tools.

Run with the memory MCP server active: python examples/flow_visual_validation_mcp.py
The output folder contains strict-validated schematics and a comparison report.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from dense_neighborhood_reflow_mcp import build_demo as build_dense
from flow_orientation_mcp import URL, call, routed

from coppermind.schematic.composer import _child, _parse_sexpr


def snapshot(path: Path) -> dict:
    """Read exported geometry for comparison; never manufacture wire coordinates."""
    root = _parse_sexpr(path.read_text(encoding="utf-8"))
    symbols = {}
    length = 0.0
    for node in root:
        if not isinstance(node, list) or not node:
            continue
        if node[0] == "symbol":
            reference = next(
                n[2] for n in node if isinstance(n, list) and n[:2] == ["property", "Reference"]
            )
            symbols[reference] = {
                "at": [float(v) for v in _child(node, "at")[1:]],
                "fields": [n for n in node if isinstance(n, list) and n[0] == "property"],
            }
        elif node[0] == "wire":
            points = _child(node, "pts")[1:]
            a, b = points
            length += abs(float(a[1]) - float(b[1])) + abs(float(a[2]) - float(b[2]))
    return {"symbols": symbols, "total_wire_length_mm": round(length, 3)}


async def export(session: ClientSession, path: Path) -> dict:
    result = await routed(session, "schematic_export_current", {"path": str(path)})
    if not result.get("ok") or result["validation"]["blocking"]:
        raise RuntimeError(f"Strict export blocked: {result}")
    return result


async def build_divider(session: ClientSession, output: Path) -> dict:
    await call(
        session, "project_create", {"name": "vertical_divider", "width_mm": 130, "height_mm": 150}
    )
    await call(
        session,
        "component_add",
        {"reference": "J1", "symbol": "Connector_Generic:Conn_01x01", "value": "INPUT"},
    )
    for name in ("VIN", "VOUT", "GND"):
        await call(session, "create_net", {"name": name})
    for ref, value in (("R1", "10k"), ("R2", "20k")):
        await call(
            session, "component_add", {"reference": ref, "symbol": "Device:R", "value": value}
        )
    await routed(
        session,
        "component_place_relative",
        {"reference": "R1", "anchor": "J1", "direction": "below", "gap_mm": 30.48},
    )
    await call(session, "connect_pins", {"net": "VOUT", "pins": ["R1.2", "R2.1"]})
    placed = await routed(
        session,
        "component_place_flow",
        {"reference": "R2", "anchor": "R1", "directions": ["below"], "gap_mm": 30.48},
    )
    await call(
        session,
        "component_add",
        {"reference": "J2", "symbol": "Connector_Generic:Conn_01x01", "value": "RETURN"},
    )
    await routed(
        session,
        "component_place_relative",
        {"reference": "J2", "anchor": "R2", "direction": "below", "gap_mm": 30.48},
    )
    for net, pins in (("VIN", ["J1.1", "R1.1"]), ("GND", ["R2.2", "J2.1"])):
        await routed(session, "connect_incremental", {"net": net, "pins": pins})
    before = output / "divider_before.kicad_sch"
    await export(session, before)
    orientations = {}
    for ref in ("R1", "R2"):
        orientations[ref] = await routed(
            session, "component_orient_flow", {"reference": ref, "force": True}
        )
    after = output / "divider_after.kicad_sch"
    validated = await export(session, after)
    old, new = snapshot(before), snapshot(after)
    resistors = [new["symbols"][ref]["at"] for ref in ("R1", "R2")]
    if not (
        resistors[0][0] == resistors[1][0]
        and resistors[0][1] < resistors[1][1]
        and all(at[2] in (0, 180) for at in resistors)
    ):
        raise RuntimeError(f"Divider is not vertical: {new}")
    for ref in ("J1", "J2"):
        if old["symbols"][ref] != new["symbols"][ref]:
            raise RuntimeError(f"External symbol changed: {ref}")
    return {
        "before": old,
        "after": new,
        "placement": placed,
        "orientations": orientations,
        "validation": validated["validation"],
    }


async def build_cases(session: ClientSession, output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    divider = await build_divider(session, output)
    before = output / "dense_before.kicad_sch"
    await build_dense(session, before)
    old = snapshot(before)
    oriented = await routed(session, "component_orient_flow", {"reference": "R9"})
    after = output / "dense_after.kicad_sch"
    validated = await export(session, after)
    new = snapshot(after)
    for ref in old["symbols"]:
        if ref != "R9" and old["symbols"][ref] != new["symbols"][ref]:
            raise RuntimeError(f"Accepted dense symbol changed: {ref}")
    if old["symbols"]["R9"]["at"][:2] != new["symbols"]["R9"]["at"][:2]:
        raise RuntimeError("Orientation moved R9")
    report = {
        "divider": divider,
        "dense": {
            "before": old,
            "after": new,
            "orientation": oriented,
            "validation": validated["validation"],
        },
    }
    (output / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Visual comparison generated:", output)
    return report


async def main() -> None:
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await build_cases(session, Path.cwd() / "flow_visual_validation")


if __name__ == "__main__":
    asyncio.run(main())

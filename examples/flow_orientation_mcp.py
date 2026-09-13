"""Demonstrate flow-aware component orientation through the CopperMind MCP.

Run from the repository root while the Streamable HTTP MCP server is running:

    python examples/flow_orientation_mcp.py

The three resistors are first positioned left-to-right while still using their
library-default vertical orientation. Semantic connectivity is then declared and
``component_orient_auto`` rotates each part to follow the electrical flow while
rerouting only the nets attached to that part.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
OUTPUT = Path.cwd() / "flow_orientation_demo.kicad_sch"


async def call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
):
    result = await session.call_tool(name, arguments or {})
    text = "".join(item.text for item in result.content if hasattr(item, "text"))
    try:
        data = json.loads(text)
    except Exception:
        data = text
    print(f"\n>>> {name}")
    print(json.dumps(data, indent=2, ensure_ascii=False) if isinstance(data, (dict, list)) else data)
    if getattr(result, "isError", False):
        raise RuntimeError(f"MCP tool {name!r} failed: {data}")
    return data


async def routed(session: ClientSession, name: str, arguments: dict[str, Any] | None = None):
    return await call(
        session,
        "execute_tool",
        {"name": name, "arguments": arguments or {}},
    )


async def main() -> None:
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            await call(
                session,
                "project_create",
                {"name": "flow_orientation_demo", "width_mm": 140, "height_mm": 90},
            )
            for net in ("N12", "N23"):
                await call(session, "create_net", {"name": net})
            for reference, value in (("R1", "10k"), ("R2", "22k"), ("R3", "47k")):
                await call(
                    session,
                    "component_add",
                    {"reference": reference, "symbol": "Device:R", "value": value},
                )

            await routed(
                session,
                "component_place_relative",
                {"reference": "R2", "anchor": "R1", "direction": "right", "gap_mm": 38.1, "lock": False},
            )
            await routed(
                session,
                "component_place_relative",
                {"reference": "R3", "anchor": "R2", "direction": "right", "gap_mm": 38.1, "lock": False},
            )

            await call(session, "connect_pins", {"net": "N12", "pins": ["R1.2", "R2.1"]})
            await call(session, "connect_pins", {"net": "N23", "pins": ["R2.2", "R3.1"]})

            oriented = {}
            for reference in ("R1", "R2", "R3"):
                oriented[reference] = await routed(
                    session,
                    "component_orient_auto",
                    {"reference": reference},
                )

            checkpoint = await routed(
                session,
                "schematic_checkpoint",
                {"run_external": False},
            )
            if not isinstance(checkpoint, dict) or not checkpoint.get("committed"):
                raise RuntimeError(f"semantic checkpoint blocked: {checkpoint}")

            exported = await routed(
                session,
                "schematic_export_current",
                {"path": str(OUTPUT), "run_external": False},
            )
            if not isinstance(exported, dict) or not exported.get("ok"):
                raise RuntimeError(f"export failed: {exported}")

            print("\n=== FLOW ORIENTATION COMPLETE ===")
            for reference in ("R1", "R2", "R3"):
                item = oriented[reference]
                print(
                    f"{reference}: rotation={item.get('chosen_rotation')}° "
                    f"flow_penalty={item.get('flow_penalty')} "
                    f"route_length={item.get('route_length_mm')}mm"
                )
            print("Generated:", OUTPUT)
            print("Semantic validation:", exported.get("validated"))


if __name__ == "__main__":
    asyncio.run(main())

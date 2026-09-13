"""Build a left-to-right resistor chain with automatic electrical-flow orientation.

Run from the repository root while the Streamable HTTP MCP server is running:

    python examples/flow_orientation_mcp.py

The target visual result is a conventional series signal chain: R1, R2 and R3
horizontal, with N12 and N23 running left-to-right through the resistor pins.
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


async def routed(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
):
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
                {"name": "flow_orientation_demo", "width_mm": 160, "height_mm": 90},
            )
            for net in ("N12", "N23"):
                await call(session, "create_net", {"name": net})
            for reference, value in (("R1", "10k"), ("R2", "22k"), ("R3", "47k")):
                await call(
                    session,
                    "component_add",
                    {"reference": reference, "symbol": "Device:R", "value": value},
                )

            # Declare electrical intent before materializing geometry. The flow
            # placement tool chooses the local position and then rotates the
            # real KiCad symbol so its pin axis follows the intended signal flow.
            await call(
                session,
                "connect_pins",
                {"net": "N12", "pins": ["R1.2", "R2.1"]},
            )
            r2 = await routed(
                session,
                "component_place_flow",
                {
                    "reference": "R2",
                    "anchor": "R1",
                    "gap_mm": 30.48,
                    "directions": ["right"],
                },
            )

            await call(
                session,
                "connect_pins",
                {"net": "N23", "pins": ["R2.2", "R3.1"]},
            )
            r3 = await routed(
                session,
                "component_place_flow",
                {
                    "reference": "R3",
                    "anchor": "R2",
                    "gap_mm": 30.48,
                    "directions": ["right"],
                },
            )

            # R1 was the original anchor. Once both semantic nets are known,
            # orient it using the same flow rule and reroute only N12.
            r1 = await routed(
                session,
                "component_orient_flow",
                {"reference": "R1"},
            )

            checkpoint = await routed(session, "schematic_checkpoint", {})
            if not isinstance(checkpoint, dict) or not checkpoint.get("committed"):
                raise RuntimeError(f"strict checkpoint blocked: {checkpoint}")

            exported = await routed(
                session,
                "schematic_export_current",
                {"path": str(OUTPUT)},
            )
            if not isinstance(exported, dict) or not exported.get("ok"):
                raise RuntimeError(f"export failed: {exported}")

            print("\n=== FLOW ORIENTATION COMPLETE ===")
            for reference, result in (("R1", r1), ("R2", r2), ("R3", r3)):
                if isinstance(result, dict):
                    rotation = result.get("chosen_rotation", result.get("rotation"))
                    axis = result.get("flow_axis", result.get("display_axis"))
                else:
                    rotation = axis = None
                print(f"{reference}: rotation={rotation}, axis={axis}")
            print("Generated:", OUTPUT)
            print("Final validated:", exported.get("validated"))


if __name__ == "__main__":
    asyncio.run(main())

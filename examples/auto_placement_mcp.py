"""Build a small schematic using CopperMind's cost-based local auto placement.

Run from the repository root while the Streamable HTTP MCP server is running:

    python examples/auto_placement_mcp.py

The example follows the intended incremental agent loop: electrical intent is
first declared with semantic ``connect_pins`` calls, then ``component_place_auto``
chooses a relative position and materializes only the affected net geometry.
This avoids routing a component while it is still at its temporary add position.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
OUTPUT = Path.cwd() / "auto_placement_demo.kicad_sch"


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
                {"name": "auto_placement_demo", "width_mm": 120, "height_mm": 90},
            )
            for net in ("N1", "N2", "N3"):
                await call(session, "create_net", {"name": net})
            for reference, value in (("R1", "10k"), ("R2", "22k"), ("R3", "47k")):
                await call(
                    session,
                    "component_add",
                    {"reference": reference, "symbol": "Device:R", "value": value},
                )

            # Declare N2 semantically first. Auto placement now owns both the
            # placement choice and first materialization of N2 geometry.
            await call(
                session,
                "connect_pins",
                {"net": "N2", "pins": ["R1.2", "R2.1"]},
            )
            r2 = await routed(
                session,
                "component_place_auto",
                {"reference": "R2", "anchor": "R1", "gap_mm": 25.4},
            )

            # R3 participates in two nets. Neither is routed at R3's temporary
            # add position; the auto placer evaluates positions while routing
            # both semantic nets on isolated snapshots.
            await call(
                session,
                "connect_pins",
                {"net": "N3", "pins": ["R2.2", "R3.1"]},
            )
            await call(
                session,
                "connect_pins",
                {"net": "N1", "pins": ["R1.1", "R3.2"]},
            )
            r3 = await routed(
                session,
                "component_place_auto",
                {"reference": "R3", "anchor": "R2", "gap_mm": 25.4},
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

            print("\n=== AUTO PLACEMENT COMPLETE ===")
            print("R2 direction:", r2.get("chosen_direction") if isinstance(r2, dict) else None)
            print("R3 direction:", r3.get("chosen_direction") if isinstance(r3, dict) else None)
            print("Generated:", OUTPUT)
            print("Final validated:", exported.get("validated"))


if __name__ == "__main__":
    asyncio.run(main())

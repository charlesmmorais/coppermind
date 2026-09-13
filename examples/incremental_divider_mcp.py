"""Build a small schematic incrementally through the CopperMind MCP.

This demonstrates the intended agent loop without invoking the global composer:

    add -> place relative -> connect/reroute one net -> checkpoint -> repeat

Requirements:
- CopperMind Streamable HTTP server at http://127.0.0.1:8765/mcp
- KiCad symbol libraries available to CopperMind
- KiCad CLI on PATH for strict ERC/final export validation

Run from the repository root:

    python -m examples.incremental_divider_mcp

Output:

    incremental_divider.kicad_sch
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
OUTPUT = Path.cwd() / "incremental_divider.kicad_sch"


async def call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    verbose: bool = True,
):
    result = await session.call_tool(name, arguments or {})
    text = "".join(item.text for item in result.content if hasattr(item, "text"))
    try:
        data = json.loads(text)
    except Exception:
        data = text

    if verbose:
        print(f"\n>>> {name}")
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(data)

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


def require_committed(result: Any, stage: str) -> None:
    if not isinstance(result, dict) or not result.get("committed"):
        raise RuntimeError(f"{stage} checkpoint blocked: {result}")


async def main() -> None:
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Stage 0: new project. No global schematic composition is used.
            await call(
                session,
                "project_create",
                {"name": "incremental_divider", "width_mm": 120, "height_mm": 80},
            )

            # Stage 1: input connector + first resistor + VIN.
            await call(
                session,
                "component_add",
                {
                    "reference": "J1",
                    "symbol": "Connector_Generic:Conn_01x02",
                    "value": "INPUT",
                },
            )
            await call(
                session,
                "component_add",
                {"reference": "R1", "symbol": "Device:R", "value": "10k"},
            )
            await routed(
                session,
                "component_place_relative",
                {
                    "reference": "R1",
                    "anchor": "J1",
                    "direction": "right",
                    "gap_mm": 38.1,
                },
            )
            await call(session, "create_net", {"name": "VIN"})
            await routed(
                session,
                "connect_incremental",
                {"net": "VIN", "pins": ["J1.1", "R1.1"]},
            )
            stage1 = await routed(
                session,
                "schematic_checkpoint",
                {"allow_incomplete": True},
            )
            require_committed(stage1, "VIN")

            # Stage 2: second resistor + output connector + VOUT.
            await call(
                session,
                "component_add",
                {"reference": "R2", "symbol": "Device:R", "value": "10k"},
            )
            await routed(
                session,
                "component_place_relative",
                {
                    "reference": "R2",
                    "anchor": "R1",
                    "direction": "below",
                    "gap_mm": 25.4,
                },
            )
            await call(
                session,
                "component_add",
                {
                    "reference": "J2",
                    "symbol": "Connector_Generic:Conn_01x01",
                    "value": "VOUT",
                },
            )
            await routed(
                session,
                "component_place_relative",
                {
                    "reference": "J2",
                    "anchor": "R1",
                    "direction": "right",
                    "gap_mm": 38.1,
                },
            )
            await call(session, "create_net", {"name": "VOUT"})
            await routed(
                session,
                "connect_incremental",
                {"net": "VOUT", "pins": ["R1.2", "R2.1", "J2.1"]},
            )
            stage2 = await routed(
                session,
                "schematic_checkpoint",
                {"allow_incomplete": True},
            )
            require_committed(stage2, "VOUT")

            # Stage 3: close the return path. This checkpoint is strict.
            await call(session, "create_net", {"name": "GND"})
            await routed(
                session,
                "connect_incremental",
                {"net": "GND", "pins": ["R2.2", "J1.2"]},
            )
            final_checkpoint = await routed(session, "schematic_checkpoint", {})
            require_committed(final_checkpoint, "final")

            await routed(
                session,
                "component_freeze_placement",
                {"references": ["J1", "R1", "R2", "J2"]},
            )

            exported = await routed(
                session,
                "schematic_export_current",
                {"path": str(OUTPUT)},
            )
            if not isinstance(exported, dict) or not exported.get("ok"):
                raise RuntimeError(f"incremental export failed: {exported}")

            print("\n=== INCREMENTAL BUILD COMPLETE ===")
            print("Generated:", OUTPUT)
            print("Global composer invoked: no")
            print("Final validated:", exported.get("validated"))


if __name__ == "__main__":
    asyncio.run(main())

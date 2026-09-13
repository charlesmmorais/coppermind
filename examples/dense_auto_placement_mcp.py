"""Build the dense VIN/VOUT/FB/SENSE stress case with automatic placement.

This is the semantic-first counterpart to ``dense_incremental_mcp.py``. The
agent declares electrical intent with ``connect_pins`` and lets
``component_place_auto`` choose each new component's local direction while
preserving accepted unrelated geometry.

Run from the repository root while the Streamable HTTP MCP server is running:

    python examples/dense_auto_placement_mcp.py

Output:

    dense_auto_placement.kicad_sch
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
OUTPUT = Path.cwd() / "dense_auto_placement.kicad_sch"


async def call(session: ClientSession, name: str, arguments: dict[str, Any] | None = None):
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
    return await call(session, "execute_tool", {"name": name, "arguments": arguments or {}})


async def add_resistor(session: ClientSession, reference: str, value: str = "10k") -> None:
    await call(session, "component_add", {"reference": reference, "symbol": "Device:R", "value": value})


async def connect_semantic(session: ClientSession, net: str, *pins: str) -> None:
    await call(session, "connect_pins", {"net": net, "pins": list(pins)})


async def auto_place(session: ClientSession, reference: str, anchor: str, gap_mm: float = 25.4) -> dict[str, Any]:
    result = await routed(
        session,
        "component_place_auto",
        {"reference": reference, "anchor": anchor, "gap_mm": gap_mm},
    )
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"auto placement failed for {reference}: {result}")
    print(
        f"AUTO {reference}: {result.get('chosen_direction')} "
        f"score={result.get('score')} rerouted={result.get('rerouted_nets')}"
    )
    return result


def require_checkpoint(result: Any, stage: str) -> None:
    if not isinstance(result, dict) or not result.get("committed"):
        raise RuntimeError(f"{stage} checkpoint blocked: {result}")


async def checkpoint(session: ClientSession, stage: str, *, strict: bool = False) -> None:
    result = await routed(
        session,
        "schematic_checkpoint",
        {} if strict else {"allow_incomplete": True},
    )
    require_checkpoint(result, stage)


async def main() -> None:
    placements: dict[str, dict[str, Any]] = {}
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await call(session, "project_create", {"name": "dense_auto_placement", "width_mm": 180, "height_mm": 110})
            for net in ("VIN", "VOUT", "FB", "SENSE", "GND"):
                await call(session, "create_net", {"name": net})

            await add_resistor(session, "R1", "10k")

            await add_resistor(session, "R2", "20k")
            await connect_semantic(session, "VOUT", "R1.2", "R2.1")
            placements["R2"] = await auto_place(session, "R2", "R1")
            await checkpoint(session, "stage-1")

            await add_resistor(session, "R3", "47k")
            await connect_semantic(session, "VOUT", "R1.2", "R3.1")
            await connect_semantic(session, "GND", "R2.2", "R3.2")
            placements["R3"] = await auto_place(session, "R3", "R2")
            await checkpoint(session, "stage-2")

            await add_resistor(session, "R4", "100k")
            await connect_semantic(session, "VOUT", "R1.2", "R4.1")
            placements["R4"] = await auto_place(session, "R4", "R1")

            await add_resistor(session, "R5", "10k")
            await connect_semantic(session, "FB", "R4.2", "R5.1")
            await connect_semantic(session, "GND", "R2.2", "R5.2")
            placements["R5"] = await auto_place(session, "R5", "R4")
            await checkpoint(session, "stage-3")

            await add_resistor(session, "R6", "10k")
            await connect_semantic(session, "FB", "R4.2", "R6.1")
            await connect_semantic(session, "GND", "R2.2", "R6.2")
            placements["R6"] = await auto_place(session, "R6", "R5")
            await checkpoint(session, "stage-4")

            await add_resistor(session, "R7", "4.7k")
            await connect_semantic(session, "VOUT", "R1.2", "R7.1")
            placements["R7"] = await auto_place(session, "R7", "R4")

            await add_resistor(session, "R8", "1k")
            await connect_semantic(session, "SENSE", "R7.2", "R8.1")
            await connect_semantic(session, "GND", "R2.2", "R8.2")
            placements["R8"] = await auto_place(session, "R8", "R7")
            await checkpoint(session, "stage-5")

            await add_resistor(session, "R9", "100k")
            await connect_semantic(session, "VIN", "R1.1", "R9.1")
            await connect_semantic(session, "SENSE", "R7.2", "R9.2")
            placements["R9"] = await auto_place(session, "R9", "R7")

            await checkpoint(session, "final", strict=True)
            await routed(session, "component_freeze_placement", {})
            exported = await routed(session, "schematic_export_current", {"path": str(OUTPUT)})
            if not isinstance(exported, dict) or not exported.get("ok"):
                raise RuntimeError(f"dense auto-placement export failed: {exported}")

            print("\n=== DENSE AUTO PLACEMENT COMPLETE ===")
            for reference in sorted(placements):
                result = placements[reference]
                print(f"{reference}: direction={result.get('chosen_direction')} score={result.get('score')}")
            print("Generated:", OUTPUT)
            print("Global composer invoked: no")
            print("Manual placement directions supplied: no")
            print("Final validated:", exported.get("validated"))


if __name__ == "__main__":
    asyncio.run(main())

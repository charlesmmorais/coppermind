"""Build the dense stress case, then compact only R9's semantic neighborhood.

Run from the repository root while the Streamable HTTP MCP server is running:

    python examples/dense_neighborhood_reflow_mcp.py

Output:

    dense_neighborhood_reflow.kicad_sch
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
OUTPUT = Path.cwd() / "dense_neighborhood_reflow.kicad_sch"


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


async def auto_place(session: ClientSession, reference: str, anchor: str) -> dict[str, Any]:
    result = await routed(
        session,
        "component_place_auto",
        {"reference": reference, "anchor": anchor, "gap_mm": 25.4},
    )
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"auto placement failed for {reference}: {result}")
    return result


async def checkpoint(session: ClientSession, stage: str, *, strict: bool = False) -> None:
    result = await routed(
        session,
        "schematic_checkpoint",
        {} if strict else {"allow_incomplete": True},
    )
    if not isinstance(result, dict) or not result.get("committed"):
        raise RuntimeError(f"{stage} checkpoint blocked: {result}")


async def main() -> None:
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await call(
                session,
                "project_create",
                {"name": "dense_neighborhood_reflow", "width_mm": 180, "height_mm": 110},
            )
            for net in ("VIN", "VOUT", "FB", "SENSE", "GND"):
                await call(session, "create_net", {"name": net})

            await add_resistor(session, "R1", "10k")

            await add_resistor(session, "R2", "20k")
            await connect_semantic(session, "VOUT", "R1.2", "R2.1")
            await auto_place(session, "R2", "R1")

            await add_resistor(session, "R3", "47k")
            await connect_semantic(session, "VOUT", "R1.2", "R3.1")
            await connect_semantic(session, "GND", "R2.2", "R3.2")
            await auto_place(session, "R3", "R2")

            await add_resistor(session, "R4", "100k")
            await connect_semantic(session, "VOUT", "R1.2", "R4.1")
            await auto_place(session, "R4", "R1")

            await add_resistor(session, "R5", "10k")
            await connect_semantic(session, "FB", "R4.2", "R5.1")
            await connect_semantic(session, "GND", "R2.2", "R5.2")
            await auto_place(session, "R5", "R4")

            await add_resistor(session, "R6", "10k")
            await connect_semantic(session, "FB", "R4.2", "R6.1")
            await connect_semantic(session, "GND", "R2.2", "R6.2")
            await auto_place(session, "R6", "R5")

            await add_resistor(session, "R7", "4.7k")
            await connect_semantic(session, "VOUT", "R1.2", "R7.1")
            await auto_place(session, "R7", "R4")

            await add_resistor(session, "R8", "1k")
            await connect_semantic(session, "SENSE", "R7.2", "R8.1")
            await connect_semantic(session, "GND", "R2.2", "R8.2")
            await auto_place(session, "R8", "R7")

            await add_resistor(session, "R9", "100k")
            await connect_semantic(session, "VIN", "R1.1", "R9.1")
            await connect_semantic(session, "SENSE", "R7.2", "R9.2")
            await auto_place(session, "R9", "R7")

            await checkpoint(session, "pre-reflow", strict=True)

            reflow = await routed(
                session,
                "component_reflow_neighborhood",
                {
                    "reference": "R9",
                    "max_components": 4,
                    "passes": 2,
                    "gap_mm": 25.4,
                    "min_improvement": 1.0,
                },
            )
            if not isinstance(reflow, dict) or not reflow.get("ok"):
                raise RuntimeError(f"neighborhood reflow failed: {reflow}")

            await checkpoint(session, "post-reflow", strict=True)
            exported = await routed(
                session,
                "schematic_export_current",
                {"path": str(OUTPUT)},
            )
            if not isinstance(exported, dict) or not exported.get("ok"):
                raise RuntimeError(f"reflow export failed: {exported}")

            print("\n=== DENSE NEIGHBORHOOD REFLOW COMPLETE ===")
            print("Neighborhood:", reflow.get("neighborhood"))
            print("Improved:", reflow.get("improved"))
            print("Baseline score:", reflow.get("baseline_score"))
            print("Final score:", reflow.get("score"))
            print("Score improvement:", reflow.get("score_improvement"))
            print("Baseline focus length mm:", reflow.get("baseline_focus_route_length_mm"))
            print("Final focus length mm:", reflow.get("focus_route_length_mm"))
            print("Focus route gain mm:", reflow.get("focus_route_gain_mm"))
            print("Target from:", reflow.get("target_from"))
            print("Target to:", reflow.get("target_to"))
            print("Moved components:", reflow.get("moved_components"))
            print("Movement mm:", reflow.get("movement_mm"))
            print("Generated:", OUTPUT)
            print("Global composer invoked: no")
            print("Final validated:", exported.get("validated"))


if __name__ == "__main__":
    asyncio.run(main())

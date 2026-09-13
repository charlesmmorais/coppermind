"""Build a denser schematic incrementally through the CopperMind MCP.

The circuit deliberately grows one local action at a time and stresses selective
rerouting with five named nets: VIN, VOUT, FB, SENSE and GND.  No global
schematic composer is invoked.

Topology:

    VIN -- R1 -- VOUT -- R4 -- FB -- R5 -- GND
      \          |       \-- R6 -- GND
       \         +-- R7 -- SENSE -- R8 -- GND
        \                         /
         ----------- R9 ----------

R2 and R3 are parallel VOUT-to-GND loads.  R9 is added last so VIN-to-SENSE
creates routing pressure after the earlier geometry has already been accepted.

Run from the repository root while the Streamable HTTP MCP server is running:

    python -m examples.dense_incremental_mcp

Output:

    dense_incremental.kicad_sch
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
OUTPUT = Path.cwd() / "dense_incremental.kicad_sch"


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


async def add_resistor(session: ClientSession, reference: str, value: str = "10k") -> None:
    await call(
        session,
        "component_add",
        {"reference": reference, "symbol": "Device:R", "value": value},
    )


async def place(
    session: ClientSession,
    reference: str,
    anchor: str,
    direction: str,
    gap_mm: float = 25.4,
) -> None:
    await routed(
        session,
        "component_place_relative",
        {
            "reference": reference,
            "anchor": anchor,
            "direction": direction,
            "gap_mm": gap_mm,
        },
    )


async def connect(session: ClientSession, net: str, *pins: str) -> None:
    await routed(
        session,
        "connect_incremental",
        {"net": net, "pins": list(pins)},
    )


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
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            await call(
                session,
                "project_create",
                {"name": "dense_incremental", "width_mm": 180, "height_mm": 110},
            )
            for net in ("VIN", "VOUT", "FB", "SENSE", "GND"):
                await call(session, "create_net", {"name": net})

            # Stage 1: establish the first VOUT divider leg.
            await add_resistor(session, "R1", "10k")
            await add_resistor(session, "R2", "20k")
            await place(session, "R2", "R1", "below")
            await connect(session, "VOUT", "R1.2", "R2.1")
            await checkpoint(session, "stage-1")

            # Stage 2: add a parallel VOUT-to-GND load.
            await add_resistor(session, "R3", "47k")
            await place(session, "R3", "R2", "right")
            await connect(session, "VOUT", "R1.2", "R3.1")
            await connect(session, "GND", "R2.2", "R3.2")
            await checkpoint(session, "stage-2")

            # Stage 3: feedback branch.
            await add_resistor(session, "R4", "100k")
            await place(session, "R4", "R1", "right", 38.1)
            await add_resistor(session, "R5", "10k")
            await place(session, "R5", "R4", "below")
            await connect(session, "VOUT", "R1.2", "R4.1")
            await connect(session, "FB", "R4.2", "R5.1")
            await connect(session, "GND", "R2.2", "R5.2")
            await checkpoint(session, "stage-3")

            # Stage 4: parallel feedback return.
            await add_resistor(session, "R6", "10k")
            await place(session, "R6", "R5", "right")
            await connect(session, "FB", "R4.2", "R6.1")
            await connect(session, "GND", "R2.2", "R6.2")
            await checkpoint(session, "stage-4")

            # Stage 5: sense branch.
            await add_resistor(session, "R7", "4.7k")
            await place(session, "R7", "R4", "right", 38.1)
            await add_resistor(session, "R8", "1k")
            await place(session, "R8", "R7", "below")
            await connect(session, "VOUT", "R1.2", "R7.1")
            await connect(session, "SENSE", "R7.2", "R8.1")
            await connect(session, "GND", "R2.2", "R8.2")
            await checkpoint(session, "stage-5")

            # Stage 6: add the long VIN-to-SENSE cross-link last.  The router
            # must preserve the accepted FB/VOUT/GND geometry and find a path
            # that does not touch any foreign net.
            await add_resistor(session, "R9", "100k")
            await place(session, "R9", "R7", "right", 38.1)
            await connect(session, "VIN", "R1.1", "R9.1")
            await connect(session, "SENSE", "R7.2", "R9.2")
            await checkpoint(session, "final", strict=True)

            await routed(session, "component_freeze_placement", {})
            exported = await routed(
                session,
                "schematic_export_current",
                {"path": str(OUTPUT)},
            )
            if not isinstance(exported, dict) or not exported.get("ok"):
                raise RuntimeError(f"dense incremental export failed: {exported}")

            print("\n=== DENSE INCREMENTAL BUILD COMPLETE ===")
            print("Generated:", OUTPUT)
            print("Global composer invoked: no")
            print("Final validated:", exported.get("validated"))


if __name__ == "__main__":
    asyncio.run(main())

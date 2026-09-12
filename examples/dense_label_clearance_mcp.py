"""Dense semantic schematic used to validate collision-aware net labels.

Requires a running CopperMind Streamable HTTP server at 127.0.0.1:8765/mcp.
The example deliberately creates a denser passive network with VIN, VOUT, FB,
SENSE and GND, parallel resistor branches, and a VIN->SENSE cross-coupling
branch that tends to exercise orthogonal routing near labels.

Run from the repository root:

    python -m examples.dense_label_clearance_mcp

The generated KiCad schematic is written to:

    dense_label_clearance.kicad_sch
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
OUTPUT = Path.cwd() / "dense_label_clearance.kicad_sch"


async def call(session: ClientSession, name: str, arguments: dict[str, Any] | None = None):
    print(f"\n>>> {name}")
    result = await session.call_tool(name, arguments or {})
    text = "".join(item.text for item in result.content if hasattr(item, "text"))
    try:
        data = json.loads(text)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        data = text
        print(text)

    if getattr(result, "isError", False):
        raise RuntimeError(f"MCP tool {name!r} failed")
    return data


async def main() -> None:
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            await call(
                session,
                "project_create",
                {"name": "dense_label_clearance", "width_mm": 140, "height_mm": 100},
            )

            components = [
                ("J1", "Connector_Generic:Conn_01x04", "SIGNALS"),
                ("R1", "Device:R", "10k"),
                ("R2", "Device:R", "22k"),
                ("R3", "Device:R", "47k"),
                ("R4", "Device:R", "100k"),
                ("R5", "Device:R", "33k"),
                ("R6", "Device:R", "68k"),
                ("R7", "Device:R", "4.7k"),
                ("R8", "Device:R", "12k"),
                ("R9", "Device:R", "220k"),
                ("#PWR01", "power:GND", "GND"),
                ("#FLG01", "power:PWR_FLAG", "PWR_FLAG"),
                ("#FLG02", "power:PWR_FLAG", "PWR_FLAG"),
            ]
            for reference, symbol, value in components:
                await call(
                    session,
                    "component_add",
                    {"reference": reference, "symbol": symbol, "value": value},
                )

            for net in ("VIN", "VOUT", "FB", "SENSE", "GND"):
                await call(session, "create_net", {"name": net})

            # VIN source/input and a long cross-coupling branch toward SENSE.
            await call(
                session,
                "connect_pins",
                {"net": "VIN", "pins": ["J1.1", "R1.1", "R9.1", "#FLG01.1"]},
            )

            # Main output node. R2/R3 form parallel loads and R4/R7 start two
            # secondary branches, making this deliberately denser than a divider.
            await call(
                session,
                "connect_pins",
                {
                    "net": "VOUT",
                    "pins": ["R1.2", "J1.2", "R2.1", "R3.1", "R4.1", "R7.1"],
                },
            )

            # Feedback node with two parallel return resistors.
            await call(
                session,
                "connect_pins",
                {"net": "FB", "pins": ["R4.2", "R5.1", "R6.1"]},
            )

            # Sense node receives both a local branch from VOUT and the remote
            # VIN cross-coupling resistor R9, increasing routing pressure.
            await call(
                session,
                "connect_pins",
                {"net": "SENSE", "pins": ["R7.2", "R8.1", "R9.2", "J1.3"]},
            )

            await call(
                session,
                "connect_pins",
                {
                    "net": "GND",
                    "pins": [
                        "J1.4",
                        "R2.2",
                        "R3.2",
                        "R5.2",
                        "R6.2",
                        "R8.2",
                        "#PWR01.1",
                        "#FLG02.1",
                    ],
                },
            )

            preview = await call(session, "design_preview")
            if isinstance(preview, dict) and preview.get("would_block"):
                raise RuntimeError("design_preview is blocking; inspect the pipeline above")

            committed = await call(session, "design_commit")
            if isinstance(committed, dict) and not committed.get("committed"):
                raise RuntimeError("design_commit was blocked; inspect the pipeline above")

            exported = await call(
                session,
                "execute_tool",
                {
                    "name": "schematic_export_composed",
                    "arguments": {"path": str(OUTPUT)},
                },
            )
            if isinstance(exported, dict) and not exported.get("ok", True):
                raise RuntimeError("schematic export failed")

            print(f"\nGenerated: {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())

"""Parametrizable design blocks (reusable topologies).

A design block instantiates a small, known-good circuit fragment onto the board:
components, nets, and placement. Each block returns a BlockResult that records
what it placed and the rule it embodies — so the AI proposes a *justified* block,
not a pile of parts. Blocks are pure: they mutate a Board via domain operations
and never touch KiCAD.
"""

from __future__ import annotations

from pydantic import BaseModel

from coppermind.domain import operations as ops
from coppermind.domain.models import Board


class BlockResult(BaseModel):
    block: str
    placed: list[str] = []
    nets: list[str] = []
    rule_id: str = ""
    rationale: str = ""


def add_decoupling(
    board: Board,
    ic_reference: str,
    cap_reference: str,
    value: str = "100nF",
    footprint: str = "Capacitor_SMD:C_0402_1005Metric",
    offset_mm: float = 2.0,
) -> BlockResult:
    """Place a decoupling capacitor next to an existing IC (cites EE.DECOUPLING.PER_IC)."""
    if ic_reference not in board.components:
        raise ValueError(f"IC '{ic_reference}' does not exist")
    ic = board.components[ic_reference]
    ops.add_component(
        board,
        cap_reference,
        footprint,
        ic.position.x + offset_mm,
        ic.position.y + offset_mm,
        value=value,
        layer=ic.layer,
    )
    return BlockResult(
        block="decoupling",
        placed=[cap_reference],
        rule_id="EE.DECOUPLING.PER_IC",
        rationale=f"{value} placed {offset_mm}mm from {ic_reference} for local supply decoupling",
    )


def add_led_indicator(
    board: Board,
    led_reference: str,
    resistor_reference: str,
    signal_net: str,
    x_mm: float,
    y_mm: float,
    resistor_value: str = "330",
    spacing_mm: float = 3.0,
) -> BlockResult:
    """Place an LED + series resistor and the connecting net (a classic indicator)."""
    if signal_net not in board.nets:
        ops.create_net(board, signal_net)
    ops.add_component(
        board, resistor_reference, "Resistor_SMD:R_0603_1608Metric",
        x_mm, y_mm, value=resistor_value,
    )
    ops.add_component(
        board, led_reference, "LED_SMD:LED_0603_1608Metric",
        x_mm + spacing_mm, y_mm, value="LED",
    )
    return BlockResult(
        block="led_indicator",
        placed=[resistor_reference, led_reference],
        nets=[signal_net],
        rule_id="EE.POWER.TRACE_WIDTH",
        rationale=f"series resistor {resistor_value}ohm limits LED current on net '{signal_net}'",
    )


BLOCKS = {
    "decoupling": add_decoupling,
    "led_indicator": add_led_indicator,
}

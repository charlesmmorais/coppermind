"""Pure cost-optimization helpers over supplier parts.

No network, fully testable. These encode the JLCPCB economics: Basic parts have
no per-unique assembly fee, Extended parts do — so the cheapest *total* part is
not always the cheapest unit price.
"""

from __future__ import annotations

from coppermind.integrations.suppliers.base import SupplierPart

EXTENDED_FEE_USD = 3.0  # per unique Extended part (JLCPCB assembly)


def effective_total(part: SupplierPart, qty: int) -> float:
    """Total cost for ``qty`` units including the Extended assembly fee.

    Raises ``ValueError`` when the part has no applicable price break. Callers
    that are selecting among catalog candidates should skip such parts rather
    than treating an unknown price as zero.
    """
    unit = part.unit_price(qty)
    if unit is None:
        raise ValueError(f"part '{part.part_id}' has no price for quantity {qty}")
    fee = 0.0 if part.basic else EXTENDED_FEE_USD
    return unit * qty + fee


def pick_cheapest(
    parts: list[SupplierPart],
    qty: int,
    require_stock: bool = True,
) -> SupplierPart | None:
    """Pick the cheapest in-stock part by effective total cost at ``qty``."""
    best: SupplierPart | None = None
    best_cost: float | None = None
    for part in parts:
        if require_stock and part.stock < qty:
            continue
        try:
            cost = effective_total(part, qty)
        except ValueError:
            continue
        if best_cost is None or cost < best_cost:
            best, best_cost = part, cost
    return best

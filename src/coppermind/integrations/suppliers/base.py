"""Supplier provider interface + part model.

One interface, many providers: an offline catalog for tests/CI/dev and a live
JLCPCB/LCSC adapter for production. The domain never imports a concrete provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class SupplierPart(BaseModel):
    part_id: str                       # e.g. LCSC "C25804"
    description: str
    package: str = ""
    manufacturer: str = ""
    mpn: str = ""
    basic: bool = False                # JLCPCB "Basic" = no assembly fee
    stock: int = 0
    datasheet: str = ""                 # datasheet URL (often via LCSC)
    # Quantity price breaks: {min_qty: unit_price}. Highest applicable break wins.
    price_breaks: dict[int, float] = {}

    def unit_price(self, qty: int) -> float | None:
        applicable = [p for q, p in self.price_breaks.items() if qty >= q]
        return min(applicable) if applicable else None


class SupplierProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def search(self, query: str, package: str | None = None, basic_only: bool = False) -> list[SupplierPart]:
        ...

    @abstractmethod
    def get(self, part_id: str) -> SupplierPart | None:
        ...

    @abstractmethod
    def alternatives(self, part_id: str) -> list[SupplierPart]:
        ...

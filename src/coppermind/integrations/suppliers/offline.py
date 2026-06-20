"""Offline catalog provider — a small built-in catalog for dev/CI/tests.

Implements the SupplierProvider interface with no network, so supplier-driven
features (search, alternatives, cost optimization) are fully testable.
"""

from __future__ import annotations

from coppermind.integrations.suppliers.base import SupplierPart, SupplierProvider

_CATALOG: list[SupplierPart] = [
    SupplierPart(part_id="C25804", description="10k 0603 resistor", package="0603",
                 manufacturer="UNI-ROYAL", mpn="0603WAF1002T5E", basic=True, stock=500000,
                 price_breaks={1: 0.0030, 100: 0.0012, 1000: 0.0008}),
    SupplierPart(part_id="C22775", description="10k 0402 resistor", package="0402",
                 manufacturer="UNI-ROYAL", mpn="0402WGF1002TCE", basic=True, stock=800000,
                 price_breaks={1: 0.0025, 100: 0.0010, 1000: 0.0006}),
    SupplierPart(part_id="C99999", description="10k 0603 resistor (extended)", package="0603",
                 manufacturer="OtherCo", mpn="OC-10K-0603", basic=False, stock=20000,
                 price_breaks={1: 0.0010, 100: 0.0006}),
    SupplierPart(part_id="C14663", description="100nF 0402 capacitor", package="0402",
                 manufacturer="Samsung", mpn="CL05B104KO5NNNC", basic=True, stock=900000,
                 price_breaks={1: 0.0040, 100: 0.0015, 1000: 0.0009}),
    SupplierPart(part_id="C2286", description="Red LED 0603", package="0603",
                 manufacturer="Everlight", mpn="19-217/R6C", basic=False, stock=120000,
                 price_breaks={1: 0.020, 100: 0.012}),
]


class OfflineCatalogProvider(SupplierProvider):
    name = "offline"

    def search(self, query: str, package: str | None = None, basic_only: bool = False) -> list[SupplierPart]:
        q = query.lower().strip()
        out = []
        for p in _CATALOG:
            if q and q not in p.description.lower() and q not in p.part_id.lower():
                continue
            if package and p.package != package:
                continue
            if basic_only and not p.basic:
                continue
            out.append(p)
        return out

    def get(self, part_id: str) -> SupplierPart | None:
        return next((p for p in _CATALOG if p.part_id == part_id), None)

    def alternatives(self, part_id: str) -> list[SupplierPart]:
        ref = self.get(part_id)
        if ref is None:
            return []
        return [
            p for p in _CATALOG
            if p.part_id != part_id and ref.description.split()[0] in p.description
        ]

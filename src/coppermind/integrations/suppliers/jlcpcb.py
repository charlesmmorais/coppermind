"""JLCPCB / LCSC live provider (network-gated sketch).

Uses the public JLCSearch API (no credentials). Network calls are isolated here
and marked no-cover; the *parsing* is a pure function so it can be tested with a
captured payload. Mirrors the OfflineCatalogProvider interface exactly, so it is
a drop-in replacement in production.
"""

from __future__ import annotations

import logging

from coppermind.integrations.suppliers.base import SupplierPart, SupplierProvider

logger = logging.getLogger(__name__)

JLCSEARCH_BASE = "https://jlcsearch.tscircuit.com"


def parse_jlcsearch_part(row: dict) -> SupplierPart:
    """Pure: map one JLCSearch row to a SupplierPart (tested with a sample)."""
    breaks = {}
    for b in row.get("price", []) or []:
        try:
            breaks[int(b["qTo"] or b["qFrom"])] = float(b["price"])
        except (KeyError, TypeError, ValueError):
            continue
    return SupplierPart(
        part_id=row.get("lcsc", row.get("part_id", "")),
        description=row.get("description", ""),
        package=row.get("package", ""),
        manufacturer=row.get("manufacturer", ""),
        mpn=row.get("mfr", row.get("mpn", "")),
        basic=bool(row.get("basic", row.get("is_basic", False))),
        stock=int(row.get("stock", 0) or 0),
        datasheet=row.get("datasheet", row.get("datasheet_url", "")) or "",
        price_breaks=breaks,
    )


class JLCPCBProvider(SupplierProvider):
    name = "jlcpcb"

    def __init__(self, base_url: str = JLCSEARCH_BASE) -> None:
        self.base_url = base_url

    def _get_json(self, path: str, params: dict) -> dict:  # pragma: no cover - network
        import requests  # type: ignore import-not-found

        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def search(self, query: str, package: str | None = None, basic_only: bool = False) -> list[SupplierPart]:  # pragma: no cover - network
        data = self._get_json("/api/search", {"q": query})
        parts = [parse_jlcsearch_part(r) for r in data.get("results", [])]
        if package:
            parts = [p for p in parts if p.package == package]
        if basic_only:
            parts = [p for p in parts if p.basic]
        return parts

    def get(self, part_id: str) -> SupplierPart | None:  # pragma: no cover - network
        data = self._get_json(f"/api/parts/{part_id}", {})
        return parse_jlcsearch_part(data) if data else None

    def alternatives(self, part_id: str) -> list[SupplierPart]:  # pragma: no cover - network
        ref = self.get(part_id)
        return self.search(ref.description) if ref else []

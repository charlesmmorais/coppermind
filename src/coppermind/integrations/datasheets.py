"""Datasheet enrichment via LCSC.

Fills in datasheet URLs for components identified by their LCSC part number
(e.g. "C25804"). Two layers:

* ``resolve_datasheets`` — pure: given LCSC ids and a SupplierProvider, return
  {id: datasheet_url} using whatever the provider already knows (local catalog
  or public API both carry the field). Fully testable, no network.
* ``LCSCDatasheetClient`` — a direct LCSC product-API lookup for ids the provider
  can't resolve. The HTTP call is isolated/gated; the response ``parse`` is pure.
"""

from __future__ import annotations

import logging

from coppermind.integrations.suppliers.base import SupplierProvider

logger = logging.getLogger(__name__)

LCSC_API_BASE = "https://wmsc.lcsc.com/wmsc/product/detail"


def resolve_datasheets(lcsc_ids: list[str], provider: SupplierProvider) -> dict[str, str]:
    """Return {lcsc_id: datasheet_url} for ids the provider can resolve. Pure."""
    out: dict[str, str] = {}
    for pid in lcsc_ids:
        part = provider.get(pid)
        if part and part.datasheet:
            out[pid] = part.datasheet
    return out


def enrich_bom(bom: dict[str, str], provider: SupplierProvider) -> dict[str, str]:
    """Map component reference -> datasheet URL.

    ``bom`` maps reference -> LCSC id. Returns reference -> datasheet for the ones
    that resolve (references with no datasheet are omitted).
    """
    resolved = resolve_datasheets(list(bom.values()), provider)
    return {ref: resolved[lcsc] for ref, lcsc in bom.items() if resolved.get(lcsc)}


def parse_lcsc_datasheet(payload: dict) -> str:
    """Extract a datasheet URL from an LCSC product-detail payload. Pure."""
    data = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return ""
    # LCSC exposes the PDF under a few possible keys across API versions.
    for key in ("pdfUrl", "datasheetUrl", "datasheet", "productDatasheet"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


class LCSCDatasheetClient:
    """Direct LCSC lookup for datasheets the supplier provider doesn't carry."""

    def __init__(self, base_url: str = LCSC_API_BASE) -> None:
        self.base_url = base_url

    def get_datasheet_url(self, lcsc_id: str) -> str:  # pragma: no cover - network
        import requests  # type: ignore import-not-found

        resp = requests.get(self.base_url, params={"productCode": lcsc_id}, timeout=20)
        resp.raise_for_status()
        return parse_lcsc_datasheet(resp.json())

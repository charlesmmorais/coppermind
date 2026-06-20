"""Local JLCPCB parts catalog provider (offline SQLite).

Implements the SupplierProvider interface over a locally downloaded JLCPCB parts
database in the widely-used `jlcparts` schema (a `components` table with the full
2.5M+ catalogue). This is the "local library" mode: fast, offline, no API
credentials. The SQL builder and row parser are pure (unit-tested); the sqlite
access is thin and works against any file in that schema — including a temporary
in-memory DB, so the provider is fully tested without a network.
"""

from __future__ import annotations

import json
import os
import sqlite3

from coppermind.integrations.suppliers.base import SupplierPart, SupplierProvider


def build_search_sql(
    query: str, package: str | None, basic_only: bool, limit: int
) -> tuple[str, list]:
    """Build a parameterized SELECT against the jlcparts `components` table. Pure."""
    where = []
    params: list = []
    if query:
        where.append("description LIKE ?")
        params.append(f"%{query}%")
    if package:
        where.append("package = ?")
        params.append(package)
    if basic_only:
        where.append("basic = 1")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT lcsc, mfr, package, manufacturer, basic, description, datasheet, "
        "stock, price FROM components" + clause + " ORDER BY stock DESC LIMIT ?"
    )
    params.append(limit)
    return sql, params


def parse_jlcparts_row(row: dict) -> SupplierPart:
    """Map a jlcparts `components` row to a SupplierPart. Pure."""
    breaks: dict[int, float] = {}
    raw = row.get("price")
    if raw:
        try:
            for b in json.loads(raw):
                key = int(b.get("qFrom") or b.get("qTo") or 1)
                breaks[key] = float(b["price"])
        except (ValueError, TypeError, KeyError):
            pass
    return SupplierPart(
        part_id=f"C{row['lcsc']}",
        description=row.get("description", "") or "",
        package=row.get("package", "") or "",
        manufacturer=row.get("manufacturer", "") or "",
        mpn=row.get("mfr", "") or "",
        basic=bool(row.get("basic", 0)),
        stock=int(row.get("stock", 0) or 0),
        datasheet=row.get("datasheet", "") or "",
        price_breaks=breaks,
    )


class LocalLibraryProvider(SupplierProvider):
    name = "local"

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def is_available(self) -> bool:
        return os.path.exists(self.db_path)

    def _rows(self, sql: str, params: list) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def search(self, query: str, package: str | None = None, basic_only: bool = False) -> list[SupplierPart]:
        sql, params = build_search_sql(query, package, basic_only, limit=50)
        return [parse_jlcparts_row(r) for r in self._rows(sql, params)]

    def get(self, part_id: str) -> SupplierPart | None:
        lcsc = part_id.lstrip("Cc")
        rows = self._rows(
            "SELECT lcsc, mfr, package, manufacturer, basic, description, datasheet, "
            "stock, price FROM components WHERE lcsc = ?",
            [lcsc],
        )
        return parse_jlcparts_row(rows[0]) if rows else None

    def alternatives(self, part_id: str) -> list[SupplierPart]:
        ref = self.get(part_id)
        if ref is None or not ref.description:
            return []
        keyword = ref.description.split()[0]
        return [p for p in self.search(keyword) if p.part_id != part_id]

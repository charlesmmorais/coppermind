import json
import sqlite3

import pytest

from coppermind.integrations.suppliers.local_library import (
    LocalLibraryProvider,
    build_search_sql,
    parse_jlcparts_row,
)


@pytest.fixture()
def jlcparts_db(tmp_path):
    db = tmp_path / "jlcparts.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE components (lcsc INTEGER, mfr TEXT, package TEXT, manufacturer TEXT, "
        "basic INTEGER, description TEXT, datasheet TEXT, stock INTEGER, price TEXT)"
    )
    conn.executemany(
        "INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (25804, "0603WAF1002T5E", "0603", "UNI-ROYAL", 1, "10k 0603 resistor",
             "https://lcsc.com/ds/C25804.pdf", 500000,
             json.dumps([{"qFrom": 1, "qTo": 99, "price": 0.003}, {"qFrom": 100, "price": 0.0012}])),
            (99, "X", "0402", "Other", 0, "10k 0402 resistor", "", 2000,
             json.dumps([{"qFrom": 1, "price": 0.001}])),
        ],
    )
    conn.commit()
    conn.close()
    return str(db)


def test_build_search_sql_is_parameterized():
    sql, params = build_search_sql("10k", "0603", True, 50)
    assert "description LIKE ?" in sql and "package = ?" in sql and "basic = 1" in sql
    assert params == ["%10k%", "0603", 50]


def test_parse_row_price_breaks_and_basic():
    part = parse_jlcparts_row({
        "lcsc": 25804, "mfr": "M", "package": "0603", "manufacturer": "U", "basic": 1,
        "description": "10k", "datasheet": "u", "stock": 5,
        "price": json.dumps([{"qFrom": 1, "price": 0.003}]),
    })
    assert part.part_id == "C25804" and part.basic and part.unit_price(1) == 0.003


def test_provider_search_get_alternatives(jlcparts_db):
    prov = LocalLibraryProvider(jlcparts_db)
    assert prov.is_available()
    results = prov.search("10k")
    assert {p.part_id for p in results} == {"C25804", "C99"}
    assert results[0].part_id == "C25804"  # ordered by stock desc
    assert prov.search("10k", basic_only=True)[0].part_id == "C25804"
    part = prov.get("C25804")
    assert part.datasheet.endswith("C25804.pdf")
    assert "C99" in {p.part_id for p in prov.alternatives("C25804")}


def test_provider_unavailable_when_missing():
    assert LocalLibraryProvider("/no/such.sqlite3").is_available() is False

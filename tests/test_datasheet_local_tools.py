import json
import sqlite3

import pytest

from coppermind.integrations.suppliers.local_library import LocalLibraryProvider
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.core import project_create


@pytest.fixture()
def session_with_local(tmp_path):
    db = tmp_path / "jlcparts.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE components (lcsc INTEGER, mfr TEXT, package TEXT, manufacturer TEXT, "
        "basic INTEGER, description TEXT, datasheet TEXT, stock INTEGER, price TEXT)"
    )
    conn.execute(
        "INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?)",
        (25804, "M", "0603", "U", 1, "10k 0603", "https://lcsc.com/ds/C25804.pdf", 9, json.dumps([])),
    )
    conn.commit()
    conn.close()
    s = Session(supplier=LocalLibraryProvider(str(db)))
    project_create(s, "P", 50, 40)
    return s


def test_datasheet_and_local_tools_discoverable():
    names = set(REGISTRY.names)
    assert {"datasheet_get", "datasheet_enrich"} <= names
    assert "datasheet" in REGISTRY.list_categories()


def test_datasheet_get_via_local_provider(session_with_local):
    out = REGISTRY.execute_tool(session_with_local, "datasheet_get", {"part_id": "C25804"})
    assert out["datasheet"].endswith("C25804.pdf")


def test_datasheet_enrich_bom(session_with_local):
    out = REGISTRY.execute_tool(
        session_with_local, "datasheet_enrich", {"bom": {"R1": "C25804", "R2": "C0000"}}
    )
    assert out["datasheets"] == {"R1": "https://lcsc.com/ds/C25804.pdf"}


def test_supplier_search_via_local(session_with_local):
    out = REGISTRY.execute_tool(session_with_local, "supplier_search", {"query": "10k"})
    assert out["provider"] == "local"
    assert out["parts"][0]["part_id"] == "C25804"

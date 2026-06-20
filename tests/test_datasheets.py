from coppermind.integrations.datasheets import (
    enrich_bom,
    parse_lcsc_datasheet,
    resolve_datasheets,
)
from coppermind.integrations.suppliers.base import SupplierPart, SupplierProvider


class _Prov(SupplierProvider):
    name = "fake"
    _data = {
        "C1": SupplierPart(part_id="C1", description="d", datasheet="https://lcsc/C1.pdf"),
        "C2": SupplierPart(part_id="C2", description="d"),  # no datasheet
    }

    def search(self, query, package=None, basic_only=False):
        return list(self._data.values())

    def get(self, part_id):
        return self._data.get(part_id)

    def alternatives(self, part_id):
        return []


def test_resolve_only_returns_known_datasheets():
    out = resolve_datasheets(["C1", "C2", "C3"], _Prov())
    assert out == {"C1": "https://lcsc/C1.pdf"}


def test_enrich_bom_maps_references():
    out = enrich_bom({"R1": "C1", "R2": "C2", "R3": "C3"}, _Prov())
    assert out == {"R1": "https://lcsc/C1.pdf"}


def test_parse_lcsc_datasheet_variants():
    assert parse_lcsc_datasheet({"result": {"pdfUrl": "u"}}) == "u"
    assert parse_lcsc_datasheet({"datasheetUrl": "v"}) == "v"
    assert parse_lcsc_datasheet({"result": {}}) == ""
    assert parse_lcsc_datasheet({}) == ""

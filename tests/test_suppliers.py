from coppermind.integrations.suppliers.base import SupplierPart
from coppermind.integrations.suppliers.jlcpcb import parse_jlcsearch_part
from coppermind.integrations.suppliers.offline import OfflineCatalogProvider
from coppermind.integrations.suppliers.optimize import effective_total, pick_cheapest


def test_unit_price_uses_best_applicable_break():
    p = SupplierPart(part_id="X", description="d", price_breaks={1: 0.01, 100: 0.004, 1000: 0.002})
    assert p.unit_price(1) == 0.01
    assert p.unit_price(150) == 0.004
    assert p.unit_price(5000) == 0.002


def test_effective_total_adds_extended_fee():
    basic = SupplierPart(part_id="B", description="d", basic=True, stock=1000, price_breaks={1: 0.01})
    ext = SupplierPart(part_id="E", description="d", basic=False, stock=1000, price_breaks={1: 0.001})
    assert effective_total(basic, 10) == 0.1          # 10 * 0.01, no fee
    assert effective_total(ext, 10) == 0.001 * 10 + 3.0  # cheaper unit, +$3 fee


def test_pick_cheapest_prefers_basic_when_fee_dominates():
    parts = [
        SupplierPart(part_id="B", description="d", basic=True, stock=1_000_000, price_breaks={1: 0.01}),
        SupplierPart(part_id="E", description="d", basic=False, stock=1_000_000, price_breaks={1: 0.001}),
    ]
    assert pick_cheapest(parts, 10).part_id == "B"     # fee makes extended pricier
    assert pick_cheapest(parts, 100000).part_id == "E"  # volume amortizes the fee


def test_pick_cheapest_respects_stock():
    parts = [SupplierPart(part_id="B", description="d", basic=True, stock=5, price_breaks={1: 0.01})]
    assert pick_cheapest(parts, 100) is None


def test_offline_provider_search_and_alternatives():
    prov = OfflineCatalogProvider()
    assert any(p.part_id == "C25804" for p in prov.search("10k"))
    assert prov.search("10k", basic_only=True)
    assert all(p.basic for p in prov.search("10k", basic_only=True))
    assert prov.get("C25804").manufacturer == "UNI-ROYAL"
    assert prov.get("nope") is None
    assert "C22775" in {p.part_id for p in prov.alternatives("C25804")}


def test_parse_jlcsearch_part_is_pure():
    row = {
        "lcsc": "C25804", "description": "10k 0603", "package": "0603",
        "manufacturer": "UNI-ROYAL", "mfr": "0603WAF1002T5E", "basic": True,
        "stock": 1234, "price": [{"qFrom": 1, "qTo": 99, "price": "0.003"}],
    }
    part = parse_jlcsearch_part(row)
    assert part.part_id == "C25804" and part.basic and part.stock == 1234
    assert part.price_breaks and min(part.price_breaks.values()) == 0.003

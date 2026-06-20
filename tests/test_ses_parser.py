from coppermind.domain.models import Layer
from coppermind.integrations.freerouting.sexpr import find, find_all, head, parse
from coppermind.integrations.freerouting.ses import parse_ses

SAMPLE = '''(session "b.ses"
 (routes
  (resolution um 10)
  (network_out
   (net "GND"
    (wire (path F.Cu 2500 0 0 100000 0 100000 50000))
    (via "Via[0-1]" 100000 50000))
   (net "VCC"
    (wire (path B.Cu 2000 0 0 0 80000))))))'''


def test_sexpr_parse_and_helpers():
    tree = parse("(a (b 1) (b 2) (c x))")
    assert head(tree) == "a"
    assert find(tree, "c") == ["c", "x"]
    assert len(find_all(tree, "b")) == 2


def test_parse_ses_scales_units():
    # resolution um 10 -> 1 unit = 0.1 um = 0.0001 mm
    r = parse_ses(SAMPLE)
    gnd = [t for t in r.tracks if t.net == "GND"]
    assert len(gnd) == 2                          # polyline split into 2 segments
    assert gnd[0].width == 0.25                   # 2500 * 0.0001
    assert gnd[0].start.x == 0.0 and gnd[0].end.x == 10.0   # 100000 * 0.0001
    assert gnd[0].layer == Layer.F_CU


def test_parse_ses_vias_and_layers():
    r = parse_ses(SAMPLE)
    assert len(r.vias) == 1
    assert r.vias[0].net == "GND"
    assert r.vias[0].position == (r.vias[0].position.__class__(x=10.0, y=5.0))
    vcc = [t for t in r.tracks if t.net == "VCC"]
    assert vcc and vcc[0].layer == Layer.B_CU


def test_parse_ses_empty_or_garbage():
    assert parse_ses("(session)").tracks == []
    assert parse_ses("(session (routes (resolution um 1)))").vias == []

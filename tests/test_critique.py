from coppermind.domain import operations as ops
from coppermind.intelligence.critique import critique, is_power_net
from coppermind.verification.checks import Severity, has_blocking


def test_power_net_detection():
    assert is_power_net("GND") and is_power_net("+3V3") and is_power_net("VBUS")
    assert not is_power_net("LED1") and not is_power_net("SDA")


def test_thin_power_trace_flagged_with_citation():
    b = ops.create_board("b", 50, 40)
    ops.create_net(b, "+5V")
    ops.create_net(b, "GND")
    ops.route_track(b, "+5V", (1, 1), (10, 1), width=0.1)  # too thin for 0.5A
    findings = critique(b, assumed_current_a=0.5)
    pw = [f for f in findings if f.code == "EE.POWER.TRACE_WIDTH"]
    assert pw and pw[0].severity == Severity.WARNING
    assert "IPC-2221" in pw[0].rule


def test_decoupling_missing_then_satisfied():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "U1", "LQFP-48", 20, 20)
    assert any(f.code == "EE.DECOUPLING.PER_IC" for f in critique(b))
    ops.add_component(b, "C1", "C_0402", 21, 21)  # within 5mm
    assert not any(f.code == "EE.DECOUPLING.PER_IC" for f in critique(b))


def test_missing_gnd_flagged():
    b = ops.create_board("b", 50, 40)
    ops.create_net(b, "+5V")
    assert any(f.code == "EE.GROUNDING.GND_PRESENT" for f in critique(b))
    ops.create_net(b, "GND")
    assert not any(f.code == "EE.GROUNDING.GND_PRESENT" for f in critique(b))


def test_critique_never_blocks_commit():
    b = ops.create_board("b", 50, 40)
    ops.add_component(b, "U1", "LQFP-48", 20, 20)
    ops.create_net(b, "+5V")
    ops.route_track(b, "+5V", (1, 1), (10, 1), width=0.05)
    assert not has_blocking(critique(b))  # advice is never ERROR

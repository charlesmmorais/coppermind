"""Proactive design critique.

Runs the EE knowledge base over a Board and returns advisory findings, each
citing the rule that produced it. Findings are ADVISORY/WARNING only — design
advice never blocks a commit (that is the structural/native-DRC gate's job). The
findings reuse the ``Violation`` shape so they slot straight into previews.
"""

from __future__ import annotations

from coppermind.domain.models import Board
from coppermind.intelligence.knowledge import get_rule
from coppermind.intelligence.trace_width import min_trace_width_mm
from coppermind.verification.checks import Severity, Violation

# Heuristic: net names that denote a supply/return rail.
_POWER_NAMES = {
    "GND", "GNDA", "AGND", "VCC", "VDD", "VEE", "VSS", "VBUS", "VIN", "VOUT",
    "+5V", "5V", "+3V3", "3V3", "+3.3V", "+12V", "12V", "+1V8", "1V8",
}


def is_power_net(name: str) -> bool:
    n = name.upper().strip()
    if n in _POWER_NAMES:
        return True
    return n.startswith("+") or n.startswith("VBAT") or n.startswith("VDD")


def _finding(rule_id: str, severity: Severity, message: str, suggestion: str, where: str) -> Violation:
    rule = get_rule(rule_id)
    return Violation(
        severity=severity,
        code=rule_id,
        message=message,
        rule=f"{rule.title} [{rule.citation}]",
        suggestion=suggestion,
        where=where,
    )


def _check_power_trace_width(board: Board, assumed_current_a: float) -> list[Violation]:
    out: list[Violation] = []
    recommended = min_trace_width_mm(assumed_current_a)
    for idx, t in enumerate(board.tracks):
        if is_power_net(t.net) and t.width < recommended:
            out.append(
                _finding(
                    "EE.POWER.TRACE_WIDTH",
                    Severity.WARNING,
                    f"power net '{t.net}' routed at {t.width:.3f}mm (track #{idx})",
                    f"for {assumed_current_a:.1f}A on 1oz copper, 10C rise, external layer, "
                    f"IPC-2221 suggests >= {recommended:.3f}mm",
                    t.net,
                )
            )
    return out


def _check_decoupling_per_ic(board: Board, radius_mm: float) -> list[Violation]:
    out: list[Violation] = []
    caps = [c for c in board.components.values() if c.reference.upper().startswith("C")]
    for comp in board.components.values():
        if not comp.reference.upper().startswith("U"):
            continue
        near = any(comp.position.distance_to(c.position) <= radius_mm for c in caps)
        if not near:
            out.append(
                _finding(
                    "EE.DECOUPLING.PER_IC",
                    Severity.ADVISORY,
                    f"{comp.reference} has no decoupling capacitor within {radius_mm:.0f}mm",
                    "place a ~100nF capacitor next to the IC's power pin",
                    comp.reference,
                )
            )
    return out


def _check_gnd_present(board: Board) -> list[Violation]:
    has_power = any(is_power_net(n) for n in board.nets)
    has_gnd = any(n.upper() in {"GND", "GNDA", "AGND", "VSS"} for n in board.nets)
    if has_power and not has_gnd:
        return [
            _finding(
                "EE.GROUNDING.GND_PRESENT",
                Severity.ADVISORY,
                "power nets are present but no ground (GND) net is defined",
                "add a GND net and connect device grounds to it",
                "",
            )
        ]
    return []


def critique(board: Board, assumed_current_a: float = 0.5, decoupling_radius_mm: float = 5.0) -> list[Violation]:
    """Return advisory design findings, sorted by descending severity."""
    findings: list[Violation] = []
    findings += _check_power_trace_width(board, assumed_current_a)
    findings += _check_decoupling_per_ic(board, decoupling_radius_mm)
    findings += _check_gnd_present(board)
    return sorted(findings, key=lambda v: v.severity, reverse=True)

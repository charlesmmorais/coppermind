"""Pre-write structural checks plus a seed of the EE knowledge base.

Each violation cites the rule that produced it and suggests a fix, so reports
are explainable and teach the user instead of just failing.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel

from coppermind.domain.models import COPPER_LAYERS, Board, pad_absolute_position


class Severity(IntEnum):
    ADVISORY = 10
    WARNING = 20
    ERROR = 30


class Violation(BaseModel):
    severity: Severity
    code: str
    message: str
    rule: str = ""           # human/standard reference, e.g. "IPC-2221"
    suggestion: str = ""     # how to fix it
    where: str = ""          # component ref / net name / location

    def label(self) -> str:
        return f"[{self.severity.name}] {self.code}: {self.message}"


# --- Structural checks (block commit at ERROR) -----------------------------


def _check_duplicate_refs(board: Board) -> list[Violation]:
    # Dict keys can't duplicate, but guard against value/key mismatch.
    out: list[Violation] = []
    for ref, comp in board.components.items():
        if comp.reference != ref:
            out.append(
                Violation(
                    severity=Severity.ERROR,
                    code="REF_KEY_MISMATCH",
                    message=f"component stored under '{ref}' but has reference '{comp.reference}'",
                    suggestion="Use ComponentManager.add_component to keep keys consistent.",
                    where=ref,
                )
            )
    return out


def _check_within_outline(board: Board) -> list[Violation]:
    out: list[Violation] = []
    if board.outline is None:
        return out
    for ref, comp in board.components.items():
        if not board.outline.contains(comp.position):
            out.append(
                Violation(
                    severity=Severity.ERROR,
                    code="COMPONENT_OUTSIDE_BOARD",
                    message=f"{ref} at ({comp.position.x}, {comp.position.y}) is outside the board outline",
                    rule="Coppermind/geometry",
                    suggestion="Move the component inside the board outline or enlarge the board.",
                    where=ref,
                )
            )
    return out


def _aabb_overlap(board: Board) -> list[Violation]:
    out: list[Violation] = []
    comps = list(board.components.values())
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            a, b = comps[i], comps[j]
            if a.layer != b.layer:
                continue
            dx = abs(a.position.x - b.position.x)
            dy = abs(a.position.y - b.position.y)
            if dx < (a.half_size.x + b.half_size.x) and dy < (a.half_size.y + b.half_size.y):
                out.append(
                    Violation(
                        severity=Severity.ERROR,
                        code="COMPONENT_COLLISION",
                        message=f"{a.reference} and {b.reference} overlap on {a.layer.value}",
                        rule="Coppermind/geometry",
                        suggestion="Increase spacing between the two footprints.",
                        where=f"{a.reference},{b.reference}",
                    )
                )
    return out


def _check_track_nets_exist(board: Board) -> list[Violation]:
    out: list[Violation] = []
    for idx, t in enumerate(board.tracks):
        if t.net not in board.nets:
            out.append(
                Violation(
                    severity=Severity.ERROR,
                    code="TRACK_UNKNOWN_NET",
                    message=f"track #{idx} references unknown net '{t.net}'",
                    suggestion="Create the net first (net_create) before routing.",
                    where=t.net,
                )
            )
        if t.layer not in COPPER_LAYERS:
            out.append(
                Violation(
                    severity=Severity.ERROR,
                    code="TRACK_NON_COPPER_LAYER",
                    message=f"track #{idx} is on non-copper layer {t.layer.value}",
                    suggestion="Route copper on F.Cu or B.Cu.",
                    where=t.layer.value,
                )
            )
    return out


# --- EE knowledge-base rule (advisory, with citation) ----------------------


def _check_min_track_width(board: Board) -> list[Violation]:
    """Seed rule: warn on hair-thin traces (manufacturability heuristic).

    Real Coppermind computes width from current via IPC-2221; Phase 0 ships a
    simple manufacturability floor to demonstrate citable, explainable rules.
    """
    out: list[Violation] = []
    floor_mm = 0.15
    for idx, t in enumerate(board.tracks):
        if t.width < floor_mm:
            out.append(
                Violation(
                    severity=Severity.WARNING,
                    code="TRACK_TOO_THIN",
                    message=f"track #{idx} width {t.width}mm is below the {floor_mm}mm manufacturability floor",
                    rule="IPC-2221 (manufacturability heuristic)",
                    suggestion="Use >= 0.15mm for standard 1oz copper fabrication.",
                    where=t.net,
                )
            )
    return out


def _check_pad_shorts(board: Board) -> list[Violation]:
    """Pads of different nets that physically overlap on the same layer = short."""
    out: list[Violation] = []
    placed = []
    for comp in board.components.values():
        for pad in comp.pads:
            placed.append((comp.reference, pad, pad_absolute_position(comp, pad)))
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            (ra, pa, posa), (rb, pb, posb) = placed[i], placed[j]
            if pa.layer != pb.layer or not pa.net or not pb.net or pa.net == pb.net:
                continue
            if (abs(posa.x - posb.x) < (pa.size.x + pb.size.x) / 2
                    and abs(posa.y - posb.y) < (pa.size.y + pb.size.y) / 2):
                out.append(Violation(
                    severity=Severity.ERROR, code="PAD_SHORT",
                    message=f"{ra}.{pa.number} ({pa.net}) overlaps {rb}.{pb.number} ({pb.net})",
                    rule="Coppermind/connectivity",
                    suggestion="Separate the pads or put them on the same net.",
                    where=f"{ra}.{pa.number},{rb}.{pb.number}",
                ))
    return out


def _check_single_pad_nets(board: Board) -> list[Violation]:
    """A net touching only one pad is almost certainly unconnected."""
    from coppermind.domain.netlist import pin_netlist

    out: list[Violation] = []
    for net, pins in pin_netlist(board).items():
        if len(pins) == 1:
            out.append(Violation(
                severity=Severity.WARNING, code="SINGLE_PAD_NET",
                message=f"net '{net}' connects to only one pad ({pins[0]})",
                rule="Coppermind/connectivity",
                suggestion="Connect the net to at least one more pad, or remove it.",
                where=net,
            ))
    return out


_STRUCTURAL = (
    _check_duplicate_refs,
    _check_within_outline,
    _aabb_overlap,
    _check_track_nets_exist,
    _check_pad_shorts,
)
_ADVISORY = (_check_min_track_width, _check_single_pad_nets)


def verify(board: Board, include_advisory: bool = True) -> list[Violation]:
    """Run all checks and return violations sorted by descending severity."""
    violations: list[Violation] = []
    for check in _STRUCTURAL:
        violations.extend(check(board))
    if include_advisory:
        for check in _ADVISORY:
            violations.extend(check(board))
    return sorted(violations, key=lambda v: v.severity, reverse=True)


def has_blocking(violations: list[Violation]) -> bool:
    return any(v.severity >= Severity.ERROR for v in violations)

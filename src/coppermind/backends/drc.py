"""Native KiCAD DRC/ERC integration via `kicad-cli`.

Two pure, testable pieces (no subprocess, no KiCAD needed):

* ``build_drc_command`` — assemble the exact ``kicad-cli pcb drc`` invocation.
* ``parse_drc_report`` — turn the kicad-cli JSON report into Coppermind
  ``Violation`` objects, merged across ``violations``, ``unconnected_items`` and
  ``schematic_parity`` and mapped onto our severity scale.

The JSON schema (KiCAD 9/10): each entry has ``type``, ``description``,
``severity`` ("error"|"warning"|"ignore"|"exclusion"), ``excluded`` (bool) and
``items`` (each with ``uuid``, ``description``, ``pos``: {x, y}).
"""

from __future__ import annotations

from typing import Any

from coppermind.verification.checks import Severity, Violation

# kicad-cli severity string -> Coppermind severity.
_SEVERITY_MAP = {
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "ignore": Severity.ADVISORY,
    "exclusion": Severity.ADVISORY,
}


def build_drc_command(
    pcb_path: str,
    output_path: str,
    kicad_cli: str = "kicad-cli",
    schematic_parity: bool = False,
    all_track_errors: bool = True,
) -> list[str]:
    """Build the ``kicad-cli pcb drc`` argv. Pure — does not run anything."""
    cmd = [
        kicad_cli,
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-all",
        "--output",
        output_path,
    ]
    if all_track_errors:
        cmd.append("--all-track-errors")
    if schematic_parity:
        cmd.append("--schematic-parity")
    cmd.append(pcb_path)
    return cmd


def _items_location(items: list[dict[str, Any]]) -> str:
    for it in items:
        pos = it.get("pos")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            return f"({pos['x']}, {pos['y']})"
    return ""


def _entry_to_violation(entry: dict[str, Any], code_prefix: str) -> Violation:
    severity = _SEVERITY_MAP.get(str(entry.get("severity", "warning")).lower(), Severity.WARNING)
    vtype = entry.get("type", "unknown")
    items = entry.get("items", []) or []
    return Violation(
        severity=severity,
        code=f"{code_prefix}:{vtype}",
        message=entry.get("description", "").strip() or vtype,
        rule=f"KiCAD DRC ({vtype})",
        suggestion="Open the board in KiCAD and inspect the flagged items.",
        where=_items_location(items),
    )


def parse_drc_report(report: dict[str, Any], include_excluded: bool = False) -> list[Violation]:
    """Parse a kicad-cli DRC JSON report into Coppermind violations.

    Merges design-rule ``violations``, ``unconnected_items`` and
    ``schematic_parity`` into one explainable list, skipping excluded entries
    unless ``include_excluded`` is set.
    """
    out: list[Violation] = []
    sections = (
        ("violations", "DRC"),
        ("unconnected_items", "UNCONNECTED"),
        ("schematic_parity", "PARITY"),
    )
    for key, prefix in sections:
        for entry in report.get(key, []) or []:
            if entry.get("excluded") and not include_excluded:
                continue
            out.append(_entry_to_violation(entry, prefix))
    return sorted(out, key=lambda v: v.severity, reverse=True)

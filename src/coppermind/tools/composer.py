"""Routed diagnostics for the semantic schematic composer.

The normal agent path uses design_preview/design_commit, which invoke this
pipeline automatically. These tools exist for explicit diagnostics and export.
"""

from __future__ import annotations

from pathlib import Path

from coppermind.safety import validate_output_path
from coppermind.schematic.composer import compose_schematic
from coppermind.schematic.erc import evaluate_schematic
from coppermind.serialize.kicad_sch import schematic_to_kicad_sch
from coppermind.session import Session


def schematic_compose(session: Session) -> dict:
    """Rebuild drawable schematic geometry deterministically from Circuit IR."""
    report = compose_schematic(session.require_circuit(), session.require_schematic())
    return report.as_dict()


def schematic_erc(session: Session) -> dict:
    """Compose and run semantic checks plus KiCad CLI ERC when available."""
    return evaluate_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
    )


def schematic_export_composed(session: Session, path: str) -> dict:
    """Compose Circuit IR and export the resulting real KiCad .kicad_sch file."""
    report = compose_schematic(session.require_circuit(), session.require_schematic())
    if not report.ok:
        return {"ok": False, "composition": report.as_dict()}
    output = validate_output_path(path, {".kicad_sch"})
    text = schematic_to_kicad_sch(session.require_schematic(), session.symbol_resolver)
    Path(output).write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "exported": output,
        "bytes": len(text.encode("utf-8")),
        "composition": report.as_dict(),
    }


COMPOSER_ROUTED_TOOLS = (schematic_compose, schematic_erc, schematic_export_composed)

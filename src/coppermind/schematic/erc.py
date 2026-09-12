"""ERC execution and bounded automatic correction for composed schematics."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from coppermind.circuit import Circuit
from coppermind.libraries import SymbolResolver
from coppermind.schematic.composer import ComposeReport, compose_schematic
from coppermind.schematic.models import Schematic, Wire
from coppermind.serialize.kicad_sch import schematic_to_kicad_sch

_BLOCKING = {"error", "fatal"}


def _flatten_violations(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        if isinstance(payload.get("violations"), list):
            return [item for item in payload["violations"] if isinstance(item, dict)]
        for value in payload.values():
            found = _flatten_violations(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _flatten_violations(value)
            if found:
                return found
    return []


def _severity(item: dict) -> str:
    return str(item.get("severity") or item.get("level") or "warning").lower()


def _message(item: dict) -> str:
    return str(item.get("description") or item.get("message") or item.get("type") or item)


def _feedback(item: dict) -> str:
    text = _message(item).lower()
    if "power" in text and ("not driven" in text or "driver" in text):
        return "Power net is not driven; add a PWR_FLAG only when external power is intentional."
    if "not connected" in text or "unconnected" in text:
        return "Pin appears unconnected; connect it in Circuit IR or explicitly model intentional no-connect intent."
    if "multiple" in text and "output" in text:
        return "Review Circuit IR: this net appears to join incompatible output drivers."
    return "Review the reported objects in Circuit IR before applying a semantic change."


def _semantic_checks(circuit: Circuit, report: ComposeReport) -> list[dict]:
    violations: list[dict] = []
    for error in circuit.validate_references():
        violations.append({"severity": "error", "type": "INVALID_REFERENCE", "description": error})
    for error in report.unresolved_pins:
        violations.append({"severity": "error", "type": "UNRESOLVED_PIN_GEOMETRY", "description": error})
    for net in circuit.nets.values():
        if len(net.nodes) == 1:
            violations.append(
                {
                    "severity": "warning",
                    "type": "SINGLE_NODE_NET",
                    "description": f"net '{net.name}' has only one connected pin",
                }
            )
    return violations


def _safe_geometry_autofix(schematic: Schematic) -> list[str]:
    """Apply only corrections that cannot alter electrical intent."""
    corrections: list[str] = []
    unique: dict[tuple[tuple[float, float], tuple[float, float]], Wire] = {}
    for wire in schematic.wires:
        a = (wire.x1, wire.y1)
        b = (wire.x2, wire.y2)
        if a == b:
            corrections.append("removed zero-length wire")
            continue
        ordered = sorted((a, b))
        wire_key: tuple[tuple[float, float], tuple[float, float]] = (ordered[0], ordered[1])
        if wire_key in unique:
            corrections.append("removed duplicate wire")
            continue
        unique[wire_key] = wire
    schematic.wires = list(unique.values())

    seen_labels: set[tuple[str, float, float]] = set()
    labels = []
    for label in schematic.labels:
        label_key = (label.text, label.x, label.y)
        if label_key in seen_labels:
            corrections.append(f"removed duplicate label {label.text}")
            continue
        seen_labels.add(label_key)
        labels.append(label)
    schematic.labels = labels
    return corrections


def run_kicad_erc(
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    executable: str = "kicad-cli",
) -> dict:
    """Run KiCad CLI ERC against the actual generated .kicad_sch when available."""
    cli = shutil.which(executable)
    if cli is None:
        return {
            "available": False,
            "blocking": False,
            "violations": [],
            "error": f"{executable} not found",
        }

    with tempfile.TemporaryDirectory(prefix="coppermind-erc-") as tmp:
        sch_path = Path(tmp) / f"{schematic.name}.kicad_sch"
        report_path = Path(tmp) / "erc.json"
        sch_path.write_text(schematic_to_kicad_sch(schematic, resolver), encoding="utf-8")
        proc = subprocess.run(
            [
                cli,
                "sch",
                "erc",
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
                "--output",
                str(report_path),
                str(sch_path),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if proc.returncode not in (0, 5):
            return {
                "available": True,
                "blocking": True,
                "violations": [],
                "error": (proc.stderr or proc.stdout or f"kicad-cli exited {proc.returncode}").strip(),
                "returncode": proc.returncode,
            }
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "available": True,
                "blocking": True,
                "violations": [],
                "error": f"invalid ERC JSON: {exc}",
                "returncode": proc.returncode,
            }
        violations = _flatten_violations(payload)
        normalized = [
            {
                "severity": _severity(item),
                "description": _message(item),
                "feedback": _feedback(item),
                "raw": item,
            }
            for item in violations
        ]
        return {
            "available": True,
            "blocking": any(item["severity"] in _BLOCKING for item in normalized),
            "violations": normalized,
            "returncode": proc.returncode,
            "stderr": proc.stderr.strip(),
        }


def evaluate_schematic(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    run_external: bool = True,
) -> dict:
    """Compose, auto-fix safe geometry, run semantic checks and optional KiCad ERC."""
    composition = compose_schematic(circuit, schematic)
    corrections = _safe_geometry_autofix(schematic)
    semantic = _semantic_checks(circuit, composition)
    semantic_blocking = any(_severity(item) in _BLOCKING for item in semantic)
    external = run_kicad_erc(schematic, resolver) if run_external and not semantic_blocking else {
        "available": False,
        "blocking": False,
        "violations": [],
        "error": "skipped because semantic composition has blocking errors" if semantic_blocking else "disabled",
    }
    return {
        "composition": composition.as_dict(),
        "autofix": corrections,
        "semantic_violations": [dict(item, feedback=_feedback(item)) for item in semantic],
        "kicad": external,
        "blocking": semantic_blocking or bool(external.get("blocking")),
    }

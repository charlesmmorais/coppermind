"""Optional multimodal review of real KiCad schematic renders.

The deterministic Visual Reviewer remains authoritative by default.  This module
adds an opt-in visual critic that receives a PDF rendered by KiCad plus a compact
Circuit IR context.  The model can only return structured findings; it never
receives tools or executable code and cannot mutate the schematic or Circuit IR.

Enable with::

    COPPERMIND_VISUAL_PROVIDER=openai
    OPENAI_API_KEY=...

AI findings are advisory by default.  Set ``COPPERMIND_VISUAL_AI_GATE=1`` only
when you explicitly want multimodal findings to participate in commit blocking.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

from coppermind.circuit import Circuit
from coppermind.libraries import SymbolResolver
from coppermind.schematic.models import Schematic
from coppermind.serialize.kicad_sch import schematic_to_kicad_sch

_DEFAULT_MODEL = "gpt-5.6-terra"
_DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
_MAX_AI_FINDINGS = 8
_MAX_AI_PENALTY = 25.0


class MultimodalReviewer(Protocol):
    """Provider boundary for visual schematic critics."""

    name: str
    model: str

    def review_pdf(self, pdf_bytes: bytes, context: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class VisualAISettings:
    provider: str = "off"
    model: str = _DEFAULT_MODEL
    endpoint: str = _DEFAULT_ENDPOINT
    gate: bool = False
    required: bool = False
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> VisualAISettings:
        provider = os.getenv("COPPERMIND_VISUAL_PROVIDER", "off").strip().lower()
        model = os.getenv("COPPERMIND_VISUAL_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        endpoint = (
            os.getenv("COPPERMIND_OPENAI_RESPONSES_URL", _DEFAULT_ENDPOINT).strip()
            or _DEFAULT_ENDPOINT
        )
        gate = _env_bool("COPPERMIND_VISUAL_AI_GATE", False)
        required = _env_bool("COPPERMIND_VISUAL_AI_REQUIRED", False)
        try:
            timeout = float(os.getenv("COPPERMIND_VISUAL_AI_TIMEOUT", "60"))
        except ValueError:
            timeout = 60.0
        return cls(
            provider=provider,
            model=model,
            endpoint=endpoint,
            gate=gate,
            required=required,
            timeout_seconds=max(5.0, min(timeout, 180.0)),
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _extract_output_text(payload: dict[str, Any]) -> str:
    """Extract text from a raw Responses API payload without SDK coupling."""
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("multimodal reviewer did not return a JSON object") from None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("multimodal reviewer returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("multimodal reviewer JSON root must be an object")
    return value


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())[:limit]


def _normalize_findings(
    raw: Any,
    allowed_refs: set[str],
    max_findings: int = _MAX_AI_FINDINGS,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    total_penalty = 0.0
    severity_caps = {"info": 2.0, "warning": 6.0, "error": 10.0}
    for item in raw[:max_findings]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "info")).lower()
        if severity not in severity_caps:
            severity = "info"
        code_raw = re.sub(r"[^A-Z0-9_]+", "_", str(item.get("code", "VISUAL_NOTE")).upper())
        code = code_raw[:64].strip("_") or "VISUAL_NOTE"
        if not code.startswith("AI_"):
            code = f"AI_{code}"
        try:
            requested_penalty = float(item.get("penalty", 0.0))
        except (TypeError, ValueError):
            requested_penalty = 0.0
        penalty = max(0.0, min(requested_penalty, severity_caps[severity]))
        penalty = min(penalty, max(0.0, _MAX_AI_PENALTY - total_penalty))
        total_penalty += penalty

        refs_value = item.get("refs", [])
        refs = []
        if isinstance(refs_value, list):
            refs = [
                ref
                for ref in (_clean_text(value, 32) for value in refs_value)
                if ref in allowed_refs
            ][:8]
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        message = _clean_text(item.get("message"), 500)
        suggestion = _clean_text(item.get("suggestion"), 500)
        if not message:
            continue
        result.append(
            {
                "code": code,
                "severity": severity,
                "message": message,
                "penalty": round(penalty, 2),
                "refs": refs,
                "suggestion": suggestion,
                "confidence": round(max(0.0, min(confidence, 1.0)), 2),
                "source": "multimodal",
            }
        )
        if total_penalty >= _MAX_AI_PENALTY:
            break
    return result


class OpenAIVisualReviewer:
    """Multimodal critic backed by the OpenAI Responses API.

    The request contains only instructions, compact Circuit IR context and the
    KiCad-rendered PDF.  No tools are attached to the model.
    """

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout_seconds: float = 60.0,
        http_post: Any = requests.post,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        self.api_key = api_key.strip()
        self.model = model
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self._http_post = http_post

    def review_pdf(self, pdf_bytes: bytes, context: dict[str, Any]) -> dict[str, Any]:
        if not pdf_bytes.startswith(b"%PDF"):
            raise ValueError("visual reviewer expected a PDF rendered by KiCad")
        allowed_refs = {
            str(item.get("reference"))
            for item in context.get("components", [])
            if isinstance(item, dict) and item.get("reference")
        }
        developer_prompt = (
            "You are a senior electronics schematic visual reviewer. Review readability and "
            "visual organization only. Do not redesign the circuit, invent components, change "
            "nets, or claim electrical errors. Judge functional grouping, left-to-right signal "
            "flow, power-flow clarity, decoupling-component proximity as a visual convention, "
            "connector grouping, label readability, density, symmetry, and visual hierarchy. "
            "Only reference component designators present in the supplied context. Return JSON "
            "only, with keys summary and findings. findings must be an array of at most 8 objects "
            "with code, severity (info|warning|error), message, penalty (0..10), refs, suggestion, "
            "and confidence (0..1). Suggestions may move/group symbols or labels but must never "
            "change electrical connectivity."
        )
        user_text = (
            "Review the attached KiCad schematic render. Circuit IR context follows:\n"
            + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        )
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": developer_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {
                            "type": "input_file",
                            "filename": "coppermind-schematic.pdf",
                            "file_data": base64.b64encode(pdf_bytes).decode("ascii"),
                        },
                    ],
                },
            ],
            "max_output_tokens": 1800,
        }
        response = self._http_post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("multimodal provider returned a non-object response")
        text = _extract_output_text(body)
        parsed = _parse_json_object(text)
        findings = _normalize_findings(parsed.get("findings"), allowed_refs)
        return {
            "provider": self.name,
            "model": self.model,
            "response_id": _clean_text(body.get("id"), 128) or None,
            "summary": _clean_text(parsed.get("summary"), 800),
            "findings": findings,
            "penalty": round(sum(float(item["penalty"]) for item in findings), 2),
        }


def render_schematic_pdf(
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    executable: str = "kicad-cli",
) -> dict[str, Any]:
    """Render a real multi-page schematic PDF through KiCad CLI."""
    cli = shutil.which(executable)
    if cli is None:
        return {"available": False, "error": f"{executable} not found", "bytes": 0}

    with tempfile.TemporaryDirectory(prefix="coppermind-visual-ai-") as tmp:
        root = Path(tmp)
        sch_path = root / f"{schematic.name}.kicad_sch"
        pdf_path = root / f"{schematic.name}.pdf"
        sch_path.write_text(schematic_to_kicad_sch(schematic, resolver), encoding="utf-8")
        proc = subprocess.run(
            [
                cli,
                "sch",
                "export",
                "pdf",
                "--output",
                str(pdf_path),
                "--exclude-drawing-sheet",
                "--black-and-white",
                "--no-background-color",
                str(sch_path),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if proc.returncode != 0 or not pdf_path.exists():
            error = (proc.stderr or proc.stdout or f"kicad-cli exited {proc.returncode}").strip()
            return {
                "available": True,
                "error": error or "KiCad PDF export produced no file",
                "returncode": proc.returncode,
                "bytes": 0,
            }
        data = pdf_path.read_bytes()
        if not data.startswith(b"%PDF"):
            return {
                "available": True,
                "error": "KiCad PDF export did not produce a valid PDF",
                "returncode": proc.returncode,
                "bytes": len(data),
            }
        return {
            "available": True,
            "error": None,
            "returncode": proc.returncode,
            "bytes": len(data),
            "_pdf_bytes": data,
        }


def build_visual_context(circuit: Circuit, schematic: Schematic) -> dict[str, Any]:
    """Build a bounded semantic context for the visual model."""
    components = []
    for reference in sorted(circuit.components):
        component = circuit.components[reference]
        symbol = next((item for item in schematic.symbols if item.reference == reference), None)
        components.append(
            {
                "reference": reference,
                "symbol_id": component.symbol_id,
                "value": component.value,
                "x_mm": round(symbol.x, 2) if symbol is not None else None,
                "y_mm": round(symbol.y, 2) if symbol is not None else None,
            }
        )
    nets = [
        {
            "name": net.name,
            "nodes": [node.key() for node in net.nodes],
        }
        for net in (circuit.nets[name] for name in sorted(circuit.nets))
    ]
    constraints = [
        {
            "kind": item.kind,
            "targets": item.targets,
            "description": item.description,
            "hard": item.hard,
        }
        for item in circuit.constraints[:24]
    ]
    return {
        "project": circuit.name,
        "components": components[:160],
        "nets": nets[:240],
        "constraints": constraints,
        "visual_counts": {
            "symbols": len(schematic.symbols),
            "wires": len(schematic.wires),
            "labels": len(schematic.labels),
        },
    }


def _configured_reviewer(settings: VisualAISettings) -> tuple[MultimodalReviewer | None, str | None]:
    if settings.provider in {"", "off", "none", "disabled"}:
        return None, "multimodal review disabled"
    if settings.provider != "openai":
        return None, f"unsupported visual provider '{settings.provider}'"
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None, "OPENAI_API_KEY is not configured"
    return (
        OpenAIVisualReviewer(
            api_key=key,
            model=settings.model,
            endpoint=settings.endpoint,
            timeout_seconds=settings.timeout_seconds,
        ),
        None,
    )


def review_schematic_multimodal(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    *,
    settings: VisualAISettings | None = None,
    reviewer: MultimodalReviewer | None = None,
) -> dict[str, Any]:
    """Run the configured multimodal critic without mutating design state."""
    config = settings or VisualAISettings.from_env()
    provider = reviewer
    config_error: str | None = None
    if provider is None:
        provider, config_error = _configured_reviewer(config)
    if provider is None:
        return {
            "enabled": config.provider not in {"", "off", "none", "disabled"},
            "available": False,
            "provider": config.provider,
            "model": config.model,
            "gate": config.gate,
            "required": config.required,
            "blocking": bool(config.required),
            "error": config_error,
            "findings": [],
            "penalty": 0.0,
        }

    rendered = render_schematic_pdf(schematic, resolver=resolver)
    raw_pdf = rendered.pop("_pdf_bytes", None)
    if not isinstance(raw_pdf, bytes):
        return {
            "enabled": True,
            "available": False,
            "provider": provider.name,
            "model": provider.model,
            "gate": config.gate,
            "required": config.required,
            "blocking": bool(config.required),
            "error": rendered.get("error") or "schematic PDF is unavailable",
            "render": rendered,
            "findings": [],
            "penalty": 0.0,
        }

    try:
        result = provider.review_pdf(raw_pdf, build_visual_context(circuit, schematic))
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        return {
            "enabled": True,
            "available": False,
            "provider": provider.name,
            "model": provider.model,
            "gate": config.gate,
            "required": config.required,
            "blocking": bool(config.required),
            "error": _clean_text(exc, 500),
            "render": rendered,
            "findings": [],
            "penalty": 0.0,
        }

    findings = result.get("findings", []) if isinstance(result, dict) else []
    severe = any(
        isinstance(item, dict)
        and item.get("severity") == "error"
        and float(item.get("confidence", 0.0)) >= 0.7
        for item in findings
    )
    return {
        "enabled": True,
        "available": True,
        "provider": provider.name,
        "model": provider.model,
        "gate": config.gate,
        "required": config.required,
        "blocking": bool(config.gate and severe),
        "error": None,
        "render": rendered,
        **result,
    }


def apply_multimodal_review(
    pipeline: dict[str, Any],
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    *,
    settings: VisualAISettings | None = None,
    reviewer: MultimodalReviewer | None = None,
) -> dict[str, Any]:
    """Attach multimodal findings to a Phase-4 report and optionally gate it."""
    visual = pipeline.get("visual_review")
    if not isinstance(visual, dict):
        return pipeline
    review = visual.get("review")
    if not isinstance(review, dict):
        return pipeline

    ai = review_schematic_multimodal(
        circuit,
        schematic,
        resolver=resolver,
        settings=settings,
        reviewer=reviewer,
    )
    review["multimodal"] = ai
    if not ai.get("available"):
        if ai.get("blocking"):
            visual["blocking"] = True
            pipeline["blocking"] = True
        return pipeline

    deterministic_score = float(review.get("score", 100.0))
    penalty = float(ai.get("penalty", 0.0))
    score = max(0.0, deterministic_score - penalty)
    review["deterministic_score"] = round(deterministic_score, 1)
    review["score"] = round(score, 1)
    review["grade"] = _grade(score)
    review["acceptable"] = score >= float(visual.get("target_score", 85.0))
    existing = review.get("findings")
    if isinstance(existing, list):
        existing.extend(ai.get("findings", []))
    visual["target_met"] = bool(review["acceptable"])

    if ai.get("blocking"):
        review["blocking"] = True
        visual["blocking"] = True
        pipeline["blocking"] = True
    return pipeline

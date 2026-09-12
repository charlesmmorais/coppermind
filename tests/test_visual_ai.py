import base64

from coppermind.circuit import Circuit
from coppermind.schematic.models import Schematic
from coppermind.schematic.visual_ai import (
    OpenAIVisualReviewer,
    VisualAISettings,
    apply_multimodal_review,
    review_schematic_multimodal,
)


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class _FakeReviewer:
    name = "fake"
    model = "fake-vision"

    def __init__(self, severity: str = "warning", confidence: float = 0.9):
        self.severity = severity
        self.confidence = confidence

    def review_pdf(self, pdf_bytes: bytes, context: dict) -> dict:
        assert pdf_bytes.startswith(b"%PDF")
        return {
            "provider": self.name,
            "model": self.model,
            "summary": "Functional blocks could be grouped more clearly.",
            "findings": [
                {
                    "code": "AI_BLOCK_GROUPING",
                    "severity": self.severity,
                    "message": "Power and load symbols are visually dispersed.",
                    "penalty": 6.0,
                    "refs": [],
                    "suggestion": "Group the power stage more tightly.",
                    "confidence": self.confidence,
                    "source": "multimodal",
                }
            ],
            "penalty": 6.0,
        }


def _pipeline(score: float = 100.0) -> dict:
    return {
        "blocking": False,
        "visual_review": {
            "target_score": 85.0,
            "target_met": True,
            "blocking": False,
            "review": {
                "score": score,
                "grade": "A",
                "acceptable": True,
                "blocking": False,
                "findings": [],
            },
        },
    }


def test_openai_visual_reviewer_sends_pdf_and_normalizes_findings():
    captured = {}
    body = {
        "id": "resp_visual_123",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": """{
                          "summary": "Readable, but the power block is scattered.",
                          "findings": [
                            {
                              "code": "block grouping",
                              "severity": "error",
                              "message": "U1 and C1 are visually separated.",
                              "penalty": 99,
                              "refs": ["U1", "C1", "HALLUCINATED"],
                              "suggestion": "Move C1 visually closer to U1 without changing nets.",
                              "confidence": 1.4
                            }
                          ]
                        }""",
                    }
                ],
            }
        ],
    }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse(body)

    reviewer = OpenAIVisualReviewer(
        api_key="test-key",
        model="gpt-test",
        endpoint="https://example.invalid/v1/responses",
        http_post=fake_post,
    )
    result = reviewer.review_pdf(
        b"%PDF-1.7\nmock",
        {
            "components": [
                {"reference": "U1", "symbol_id": "MCU:X", "value": "MCU"},
                {"reference": "C1", "symbol_id": "Device:C", "value": "100n"},
            ]
        },
    )

    request_file = captured["json"]["input"][1]["content"][1]
    assert request_file["type"] == "input_file"
    assert base64.b64decode(request_file["file_data"]).startswith(b"%PDF")
    assert "Bearer test-key" == captured["headers"]["Authorization"]
    assert result["response_id"] == "resp_visual_123"
    assert result["findings"][0]["code"] == "AI_BLOCK_GROUPING"
    assert result["findings"][0]["penalty"] == 10.0
    assert result["findings"][0]["confidence"] == 1.0
    assert result["findings"][0]["refs"] == ["U1", "C1"]


def test_multimodal_review_is_disabled_without_provider(monkeypatch):
    monkeypatch.setenv("COPPERMIND_VISUAL_PROVIDER", "off")
    result = review_schematic_multimodal(Circuit(name="demo"), Schematic(name="demo"))
    assert result["enabled"] is False
    assert result["available"] is False
    assert result["blocking"] is False


def test_multimodal_findings_adjust_score_but_are_advisory_by_default(monkeypatch):
    monkeypatch.setattr(
        "coppermind.schematic.visual_ai.render_schematic_pdf",
        lambda *args, **kwargs: {
            "available": True,
            "error": None,
            "bytes": 16,
            "_pdf_bytes": b"%PDF-1.7\nmock",
        },
    )
    pipeline = _pipeline()
    settings = VisualAISettings(provider="openai", model="fake", gate=False)
    result = apply_multimodal_review(
        pipeline,
        Circuit(name="demo"),
        Schematic(name="demo"),
        settings=settings,
        reviewer=_FakeReviewer(severity="error"),
    )
    review = result["visual_review"]["review"]
    assert review["deterministic_score"] == 100.0
    assert review["score"] == 94.0
    assert review["multimodal"]["available"] is True
    assert review["findings"][0]["source"] == "multimodal"
    assert result["blocking"] is False


def test_multimodal_gate_can_block_on_high_confidence_error(monkeypatch):
    monkeypatch.setattr(
        "coppermind.schematic.visual_ai.render_schematic_pdf",
        lambda *args, **kwargs: {
            "available": True,
            "error": None,
            "bytes": 16,
            "_pdf_bytes": b"%PDF-1.7\nmock",
        },
    )
    pipeline = _pipeline()
    settings = VisualAISettings(provider="openai", model="fake", gate=True)
    result = apply_multimodal_review(
        pipeline,
        Circuit(name="demo"),
        Schematic(name="demo"),
        settings=settings,
        reviewer=_FakeReviewer(severity="error", confidence=0.95),
    )
    assert result["blocking"] is True
    assert result["visual_review"]["blocking"] is True
    assert result["visual_review"]["review"]["blocking"] is True

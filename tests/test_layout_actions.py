from coppermind.circuit import Circuit, Component, Constraint
from coppermind.schematic.layout_actions import (
    LayoutAction,
    LayoutActionType,
    LayoutPlan,
    apply_layout_plan,
    autofix_visual_layout,
    compare_visual_candidate,
    normalize_layout_action,
    plan_visual_actions,
)
from coppermind.schematic.models import Schematic, SchSymbol
from coppermind.schematic.visual_ai import VisualAISettings
from coppermind.tools import REGISTRY


def _design() -> tuple[Circuit, Schematic]:
    circuit = Circuit(name="layout")
    circuit.add_component(Component(reference="U1", symbol_id="Test:U"))
    circuit.add_component(Component(reference="C1", symbol_id="Test:C"))
    circuit.add_component(Component(reference="R1", symbol_id="Test:R"))
    schematic = Schematic(
        name="layout",
        symbols=[
            SchSymbol(lib_id="Test:U", reference="U1", x=25.4, y=25.4),
            SchSymbol(lib_id="Test:C", reference="C1", x=25.4, y=25.4),
            SchSymbol(lib_id="Test:R", reference="R1", x=50.8, y=25.4),
        ],
    )
    return circuit, schematic


def test_visual_finding_becomes_typed_layout_action():
    circuit, _ = _design()
    plan = plan_visual_actions(
        {
            "findings": [
                {
                    "code": "SYMBOL_OVERLAP",
                    "refs": ["U1", "C1"],
                    "message": "symbols overlap",
                }
            ]
        },
        circuit,
    )
    assert len(plan.actions) == 1
    assert plan.actions[0].type == LayoutActionType.SEPARATE_BLOCKS
    assert plan.actions[0].refs == ["U1", "C1"]


def test_untrusted_explicit_action_is_bounded_and_filters_unknown_refs():
    action = normalize_layout_action(
        {
            "type": "move_near",
            "refs": ["C1", "HALLUCINATED"],
            "target": "U1",
            "distance_mm": 999,
            "confidence": 2,
        },
        {"U1", "C1"},
    )
    assert action is not None
    assert action.refs == ["C1"]
    assert action.target == "U1"
    assert action.distance_mm == 30.48
    assert action.confidence == 1.0


def test_executor_moves_geometry_without_touching_circuit_ir():
    circuit, schematic = _design()
    before = circuit.model_dump(mode="json")
    plan = LayoutPlan(
        actions=[
            LayoutAction(
                type=LayoutActionType.SEPARATE_BLOCKS,
                refs=["U1", "C1"],
                distance_mm=12.7,
            )
        ]
    )
    result = apply_layout_plan(plan, circuit, schematic)
    positions = {item.reference: (item.x, item.y) for item in schematic.symbols}
    assert result.changed is True
    assert positions["U1"] != positions["C1"]
    assert circuit.model_dump(mode="json") == before


def test_executor_rejects_hard_position_constraint():
    circuit, schematic = _design()
    circuit.constraints.append(
        Constraint(kind="lock_position", targets=["C1"], hard=True, description="fixed")
    )
    plan = LayoutPlan(
        actions=[
            LayoutAction(
                type=LayoutActionType.MOVE_NEAR,
                refs=["C1"],
                target="U1",
                distance_mm=10.16,
            )
        ]
    )
    result = apply_layout_plan(plan, circuit, schematic)
    assert result.changed is False
    assert result.rejected
    assert "hard position constraint" in result.rejected[0]["errors"][0]


def test_candidate_gate_rejects_new_erc_or_visual_regression():
    baseline = {
        "visual_review": {"review": {"score": 80, "deterministic_score": 90}},
        "kicad": {
            "available": True,
            "blocking": False,
            "violations": [{"severity": "warning", "description": "existing"}],
        },
    }
    candidate = {
        "visual_review": {"review": {"score": 88, "deterministic_score": 89}},
        "kicad": {
            "available": True,
            "blocking": False,
            "violations": [
                {"severity": "warning", "description": "existing"},
                {"severity": "error", "description": "new"},
            ],
        },
    }
    decision = compare_visual_candidate(
        baseline,
        candidate,
        circuit_unchanged=True,
        changed=True,
        unresolved=[],
    )
    assert decision["accepted"] is False
    assert "candidate introduced new ERC violations" in decision["reasons"]
    assert "deterministic visual score regressed" in decision["reasons"]


class _PositionAwareReviewer:
    name = "fake"
    model = "fake-vision"

    def review_pdf(self, pdf_bytes: bytes, context: dict) -> dict:
        assert pdf_bytes.startswith(b"%PDF")
        positions = {item["reference"]: (item["x_mm"], item["y_mm"]) for item in context["components"]}
        ux, uy = positions["U1"]
        cx, cy = positions["C1"]
        distance = ((ux - cx) ** 2 + (uy - cy) ** 2) ** 0.5
        if distance <= 30:
            return {
                "provider": self.name,
                "model": self.model,
                "summary": "grouping is good",
                "findings": [],
                "penalty": 0.0,
            }
        return {
            "provider": self.name,
            "model": self.model,
            "summary": "decoupling is visually far away",
            "findings": [
                {
                    "code": "AI_DECOUPLING_PROXIMITY",
                    "severity": "warning",
                    "message": "C1 is visually far from U1",
                    "penalty": 6.0,
                    "refs": ["C1", "U1"],
                    "suggestion": "move C1 closer",
                    "confidence": 0.95,
                    "source": "multimodal",
                    "action": {
                        "type": "move_near",
                        "refs": ["C1"],
                        "target": "U1",
                        "distance_mm": 25.4,
                    },
                }
            ],
            "penalty": 6.0,
        }


def test_autofix_accepts_only_improving_candidate_and_preserves_ir(monkeypatch):
    circuit, schematic = _design()
    before = circuit.model_dump(mode="json")
    monkeypatch.setattr(
        "coppermind.schematic.visual_ai.render_schematic_pdf",
        lambda *args, **kwargs: {
            "available": True,
            "error": None,
            "bytes": 16,
            "_pdf_bytes": b"%PDF-1.7\nmock",
        },
    )
    result = autofix_visual_layout(
        circuit,
        schematic,
        target_score=97,
        max_iterations=2,
        run_external=False,
        settings=VisualAISettings(provider="openai", model="fake"),
        reviewer=_PositionAwareReviewer(),
    )
    assert result["accepted_iterations"] >= 1
    assert result["final_score"] >= 97
    assert result["target_met"] is True
    assert circuit.model_dump(mode="json") == before


def test_phase5_tools_are_routed_and_discoverable():
    assert "schematic_visual_plan" in REGISTRY.names
    assert "schematic_visual_apply" in REGISTRY.names
    assert "schematic_visual_autofix" in REGISTRY.names

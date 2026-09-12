"""Routed diagnostics and controlled actions for the semantic schematic composer.

The normal agent path uses design_preview/design_commit, which invoke the safe
Phase-4 pipeline automatically.  Phase-5 autonomous layout tools remain routed
on demand because they have a higher autonomy level than ordinary inspection.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from coppermind.safety import validate_output_path
from coppermind.schematic.composer import compose_schematic
from coppermind.schematic.layout_actions import (
    LayoutAction,
    LayoutPlan,
    _copy_geometry,
    _evaluate_current_geometry,
    apply_layout_plan,
    autofix_visual_layout,
    compare_visual_candidate,
    plan_visual_actions,
)
from coppermind.schematic.visual_ai import apply_multimodal_review
from coppermind.schematic.visual_review import (
    evaluate_visual_schematic,
    optimize_visual_layout,
    review_schematic_visual,
)
from coppermind.serialize.kicad_sch import schematic_to_kicad_sch
from coppermind.session import Session


def _apply_ai(session: Session, pipeline: dict) -> dict:
    return apply_multimodal_review(
        pipeline,
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
    )


def schematic_compose(session: Session) -> dict:
    """Rebuild drawable schematic geometry deterministically from Circuit IR."""
    report = compose_schematic(session.require_circuit(), session.require_schematic())
    return report.as_dict()


def schematic_erc(session: Session) -> dict:
    """Compose, visually review and run semantic checks plus KiCad CLI ERC."""
    pipeline = evaluate_visual_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
    )
    return _apply_ai(session, pipeline)


def schematic_visual_review(session: Session, include_svg: bool = False) -> dict:
    """Review readability with deterministic metrics and optional multimodal critique."""
    compose_schematic(session.require_circuit(), session.require_schematic())
    review = review_schematic_visual(
        session.require_schematic(),
        circuit=session.require_circuit(),
        resolver=session.symbol_resolver,
        include_svg=include_svg,
    )
    pipeline = {
        "blocking": bool(review["blocking"]),
        "visual_review": {
            "target_score": 85.0,
            "target_met": bool(review["score"] >= 85.0),
            "changed": False,
            "attempts": [],
            "blocking": bool(review["blocking"]),
            "review": review,
        },
    }
    enhanced = _apply_ai(session, pipeline)
    return enhanced["visual_review"]["review"]


def schematic_visual_optimize(
    session: Session,
    target_score: float = 85.0,
    max_passes: int = 4,
    include_svg: bool = False,
) -> dict:
    """Optimize geometry, then attach optional multimodal visual findings."""
    compose_schematic(session.require_circuit(), session.require_schematic())
    visual = optimize_visual_layout(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        target_score=target_score,
        max_passes=max_passes,
        include_svg=include_svg,
    )
    pipeline = {"blocking": bool(visual["blocking"]), "visual_review": visual}
    enhanced = _apply_ai(session, pipeline)
    return enhanced["visual_review"]


def schematic_visual_plan(session: Session, target_score: float = 85.0) -> dict:
    """Create a typed, bounded Layout Action IR plan from current visual findings."""
    circuit = session.require_circuit()
    schematic = session.require_schematic()
    pipeline = evaluate_visual_schematic(
        circuit,
        schematic,
        resolver=session.symbol_resolver,
        target_score=target_score,
        max_passes=4,
    )
    enhanced = _apply_ai(session, pipeline)
    visual = enhanced.get("visual_review", {})
    review = visual.get("review", {}) if isinstance(visual, dict) else {}
    plan = plan_visual_actions(review if isinstance(review, dict) else {}, circuit)
    return {
        "score": review.get("score") if isinstance(review, dict) else None,
        "target_score": target_score,
        "blocking": bool(enhanced.get("blocking")),
        "plan": plan.model_dump(mode="json"),
        "review": review,
    }


def schematic_visual_apply(
    session: Session,
    actions: list[dict],
    target_score: float = 85.0,
    run_external: bool = True,
) -> dict:
    """Apply an explicit Layout Action IR plan only when all safety gates improve it."""
    circuit = session.require_circuit()
    schematic = session.require_schematic()
    try:
        plan = LayoutPlan(
            source="explicit-mcp",
            summary="explicit bounded layout plan",
            actions=[LayoutAction.model_validate(item) for item in actions],
        )
    except ValidationError as exc:
        return {"accepted": False, "error": str(exc), "plan": None}

    baseline = evaluate_visual_schematic(
        circuit,
        schematic,
        resolver=session.symbol_resolver,
        target_score=target_score,
        max_passes=4,
        run_external=run_external,
    )
    baseline = _apply_ai(session, baseline)
    circuit_before = circuit.model_dump_json()
    candidate = schematic.model_copy(deep=True)
    execution = apply_layout_plan(plan, circuit, candidate)
    candidate_pipeline = _evaluate_current_geometry(
        circuit,
        candidate,
        session.symbol_resolver,
        target_score=target_score,
        run_external=run_external,
        settings=None,
        reviewer=None,
    )
    decision = compare_visual_candidate(
        baseline,
        candidate_pipeline,
        circuit_unchanged=circuit.model_dump_json() == circuit_before,
        changed=execution.changed,
        unresolved=execution.unresolved,
    )
    if decision["accepted"]:
        _copy_geometry(candidate, schematic)
    return {
        **decision,
        "plan": plan.model_dump(mode="json"),
        "execution": execution.model_dump(mode="json"),
        "pipeline": candidate_pipeline if decision["accepted"] else baseline,
    }


def schematic_visual_autofix(
    session: Session,
    target_score: float = 85.0,
    max_iterations: int = 3,
    run_external: bool = True,
) -> dict:
    """Run bounded review -> plan -> apply -> verify -> accept/rollback iterations."""
    return autofix_visual_layout(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        target_score=target_score,
        max_iterations=max_iterations,
        run_external=run_external,
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


COMPOSER_ROUTED_TOOLS = (
    schematic_compose,
    schematic_erc,
    schematic_visual_review,
    schematic_visual_optimize,
    schematic_visual_plan,
    schematic_visual_apply,
    schematic_visual_autofix,
    schematic_export_composed,
)

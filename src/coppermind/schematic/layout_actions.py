"""Typed geometry-only actions for Phase 5 visual auto-fix.

The Visual Reviewer may propose layout intent, but it never edits KiCad directly.
Every proposal is normalized into this small Layout Action IR, validated against
the current Circuit IR, executed on a schematic copy, rerouted, reviewed, ERC
checked and only then accepted.  Electrical intent remains immutable.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from coppermind.circuit import Circuit
from coppermind.libraries import SymbolResolver
from coppermind.schematic.models import Schematic, SchSymbol
from coppermind.schematic.visual_ai import (
    MultimodalReviewer,
    VisualAISettings,
    apply_multimodal_review,
)
from coppermind.schematic.visual_review import (
    _reroute,
    evaluate_visual_schematic,
    review_schematic_visual,
)
from coppermind.schematic.erc import run_kicad_erc

_GRID = 2.54
_DEFAULT_TARGET_SCORE = 85.0
_DEFAULT_MAX_ITERATIONS = 3
_MAX_ACTIONS = 6
_MAX_REFS = 12
_MAX_SHIFT_MM = 40.64


class LayoutActionType(str, Enum):
    MOVE_NEAR = "move_near"
    MOVE_GROUP = "move_group"
    ALIGN = "align"
    DISTRIBUTE = "distribute"
    COMPACT_BLOCK = "compact_block"
    SEPARATE_BLOCKS = "separate_blocks"


class LayoutAxis(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class LayoutSide(str, Enum):
    AUTO = "auto"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class LayoutAction(BaseModel):
    """One bounded geometry-only operation.

    ``refs`` always names existing component references.  No action can add,
    remove or reconnect a component; the executor only changes symbol positions
    and then derives wires/labels/junctions again from Circuit IR.
    """

    type: LayoutActionType
    refs: list[str] = Field(default_factory=list, min_length=1, max_length=_MAX_REFS)
    target: str | None = None
    axis: LayoutAxis | None = None
    side: LayoutSide = LayoutSide.AUTO
    distance_mm: float = Field(default=7.62, ge=_GRID, le=30.48)
    spacing_mm: float = Field(default=7.62, ge=_GRID, le=25.4)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = ""

    @model_validator(mode="after")
    def _validate_shape(self) -> LayoutAction:
        self.refs = list(dict.fromkeys(ref.strip() for ref in self.refs if ref.strip()))
        if not self.refs:
            raise ValueError("layout action requires at least one component reference")
        if self.type in {LayoutActionType.MOVE_NEAR, LayoutActionType.MOVE_GROUP}:
            if not self.target:
                raise ValueError(f"{self.type.value} requires target")
            if self.type == LayoutActionType.MOVE_GROUP and len(self.refs) < 2:
                raise ValueError("move_group requires at least two refs")
        if self.type == LayoutActionType.ALIGN and (len(self.refs) < 2 or self.axis is None):
            raise ValueError("align requires at least two refs and an axis")
        if self.type == LayoutActionType.DISTRIBUTE and (len(self.refs) < 3 or self.axis is None):
            raise ValueError("distribute requires at least three refs and an axis")
        if self.type in {LayoutActionType.COMPACT_BLOCK, LayoutActionType.SEPARATE_BLOCKS}:
            if len(self.refs) < 2:
                raise ValueError(f"{self.type.value} requires at least two refs")
        return self


class LayoutPlan(BaseModel):
    """A bounded set of visual-only actions proposed for one iteration."""

    summary: str = ""
    source: str = "visual-review"
    actions: list[LayoutAction] = Field(default_factory=list, max_length=_MAX_ACTIONS)


class LayoutExecution(BaseModel):
    changed: bool = False
    applied: list[dict[str, Any]] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


def _snap(value: float) -> float:
    return round(value / _GRID) * _GRID


def _symbols_by_ref(schematic: Schematic) -> dict[str, SchSymbol]:
    return {symbol.reference: symbol for symbol in schematic.symbols}


def _locked_refs(circuit: Circuit) -> set[str]:
    kinds = {"fixed_position", "lock_position", "position_lock", "do_not_move"}
    locked: set[str] = set()
    for constraint in circuit.constraints:
        if constraint.hard and constraint.kind.strip().lower() in kinds:
            locked.update(ref for ref in constraint.targets if ref in circuit.components)
    return locked


def _bounded_move(symbol: SchSymbol, x: float, y: float, max_shift_mm: float) -> bool:
    dx, dy = x - symbol.x, y - symbol.y
    distance = math.hypot(dx, dy)
    if distance > max_shift_mm and distance > 0:
        scale = max_shift_mm / distance
        x = symbol.x + dx * scale
        y = symbol.y + dy * scale
    x, y = _snap(x), _snap(y)
    changed = not math.isclose(symbol.x, x) or not math.isclose(symbol.y, y)
    symbol.x, symbol.y = x, y
    return changed


def _centroid(symbols: list[SchSymbol]) -> tuple[float, float]:
    return (
        sum(symbol.x for symbol in symbols) / len(symbols),
        sum(symbol.y for symbol in symbols) / len(symbols),
    )


def validate_layout_action(
    action: LayoutAction,
    circuit: Circuit,
    schematic: Schematic,
) -> list[str]:
    """Return safety violations without mutating the design."""
    errors: list[str] = []
    drawable = _symbols_by_ref(schematic)
    locked = _locked_refs(circuit)
    for ref in action.refs:
        if ref not in circuit.components:
            errors.append(f"unknown Circuit IR component '{ref}'")
        elif ref not in drawable:
            errors.append(f"component '{ref}' has no drawable schematic symbol")
        elif ref in locked:
            errors.append(f"component '{ref}' is protected by a hard position constraint")
    if action.target:
        if action.target not in circuit.components:
            errors.append(f"unknown target component '{action.target}'")
        elif action.target not in drawable:
            errors.append(f"target component '{action.target}' has no drawable schematic symbol")
        if action.target in action.refs:
            errors.append("target component cannot also be moved by the same action")
    return errors


def normalize_layout_action(raw: Any, allowed_refs: set[str]) -> LayoutAction | None:
    """Normalize an untrusted reviewer action into the strict Layout Action IR."""
    if not isinstance(raw, dict):
        return None
    try:
        action_type = LayoutActionType(str(raw.get("type", "")).strip().lower())
    except ValueError:
        return None
    refs_raw = raw.get("refs", raw.get("references", []))
    if not isinstance(refs_raw, list):
        return None
    refs = [str(ref).strip()[:32] for ref in refs_raw if str(ref).strip() in allowed_refs][:_MAX_REFS]
    target_raw = str(raw.get("target") or "").strip()[:32]
    target = target_raw if target_raw in allowed_refs else None

    axis: LayoutAxis | None = None
    axis_raw = str(raw.get("axis") or "").strip().lower()
    if axis_raw:
        try:
            axis = LayoutAxis(axis_raw)
        except ValueError:
            return None
    side_raw = str(raw.get("side") or "auto").strip().lower()
    try:
        side = LayoutSide(side_raw)
    except ValueError:
        side = LayoutSide.AUTO

    def bounded_number(name: str, default: float, low: float, high: float) -> float:
        try:
            value = float(raw.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    try:
        return LayoutAction(
            type=action_type,
            refs=refs,
            target=target,
            axis=axis,
            side=side,
            distance_mm=bounded_number("distance_mm", 7.62, _GRID, 30.48),
            spacing_mm=bounded_number("spacing_mm", 7.62, _GRID, 25.4),
            confidence=bounded_number("confidence", 1.0, 0.0, 1.0),
            rationale=str(raw.get("rationale") or "").strip()[:500],
        )
    except ValueError:
        return None


def _auto_side(moving: list[SchSymbol], target: SchSymbol) -> LayoutSide:
    cx, cy = _centroid(moving)
    dx, dy = cx - target.x, cy - target.y
    if abs(dx) >= abs(dy):
        return LayoutSide.LEFT if dx < 0 else LayoutSide.RIGHT
    return LayoutSide.TOP if dy < 0 else LayoutSide.BOTTOM


def _move_near(
    action: LayoutAction,
    symbols: dict[str, SchSymbol],
    max_shift_mm: float,
) -> bool:
    assert action.target is not None
    moving = [symbols[ref] for ref in action.refs]
    target = symbols[action.target]
    cx, cy = _centroid(moving)
    side = action.side if action.side != LayoutSide.AUTO else _auto_side(moving, target)
    distance = action.distance_mm
    target_cx, target_cy = target.x, target.y
    wanted_cx, wanted_cy = target_cx, target_cy
    if side == LayoutSide.LEFT:
        wanted_cx -= distance
    elif side == LayoutSide.RIGHT:
        wanted_cx += distance
    elif side == LayoutSide.TOP:
        wanted_cy -= distance
    else:
        wanted_cy += distance
    dx, dy = wanted_cx - cx, wanted_cy - cy
    changed = False
    for symbol in moving:
        changed |= _bounded_move(symbol, symbol.x + dx, symbol.y + dy, max_shift_mm)
    return changed


def _align(action: LayoutAction, symbols: dict[str, SchSymbol], max_shift_mm: float) -> bool:
    moving = [symbols[ref] for ref in action.refs]
    assert action.axis is not None
    changed = False
    if action.axis == LayoutAxis.HORIZONTAL:
        y = _snap(sum(symbol.y for symbol in moving) / len(moving))
        for symbol in moving:
            changed |= _bounded_move(symbol, symbol.x, y, max_shift_mm)
    else:
        x = _snap(sum(symbol.x for symbol in moving) / len(moving))
        for symbol in moving:
            changed |= _bounded_move(symbol, x, symbol.y, max_shift_mm)
    return changed


def _distribute(action: LayoutAction, symbols: dict[str, SchSymbol], max_shift_mm: float) -> bool:
    assert action.axis is not None
    moving = [symbols[ref] for ref in action.refs]
    horizontal = action.axis == LayoutAxis.HORIZONTAL
    moving.sort(key=lambda symbol: symbol.x if horizontal else symbol.y)
    values = [symbol.x if horizontal else symbol.y for symbol in moving]
    center = sum(values) / len(values)
    span = max(max(values) - min(values), action.spacing_mm * (len(moving) - 1))
    start = center - span / 2.0
    changed = False
    for index, symbol in enumerate(moving):
        value = start + (span * index / (len(moving) - 1))
        if horizontal:
            changed |= _bounded_move(symbol, value, symbol.y, max_shift_mm)
        else:
            changed |= _bounded_move(symbol, symbol.x, value, max_shift_mm)
    return changed


def _compact_block(action: LayoutAction, symbols: dict[str, SchSymbol], max_shift_mm: float) -> bool:
    moving = [symbols[ref] for ref in sorted(action.refs)]
    cx, cy = _centroid(moving)
    columns = min(3, max(2, int(math.ceil(math.sqrt(len(moving))))))
    rows = int(math.ceil(len(moving) / columns))
    x_step = max(action.spacing_mm, 15.24)
    y_step = max(action.spacing_mm, 12.7)
    changed = False
    for index, symbol in enumerate(moving):
        col = index % columns
        row = index // columns
        x = cx + (col - (columns - 1) / 2.0) * x_step
        y = cy + (row - (rows - 1) / 2.0) * y_step
        changed |= _bounded_move(symbol, x, y, max_shift_mm)
    return changed


def _separate_blocks(action: LayoutAction, symbols: dict[str, SchSymbol], max_shift_mm: float) -> bool:
    if len(action.refs) > 2:
        distributed = action.model_copy(update={"type": LayoutActionType.DISTRIBUTE, "axis": LayoutAxis.HORIZONTAL})
        return _distribute(distributed, symbols, max_shift_mm)
    left, right = (symbols[action.refs[0]], symbols[action.refs[1]])
    if left.x > right.x:
        left, right = right, left
    center = (left.x + right.x) / 2.0
    separation = max(action.distance_mm * 2.0, abs(right.x - left.x), 20.32)
    changed = _bounded_move(left, center - separation / 2.0, left.y, max_shift_mm)
    changed |= _bounded_move(right, center + separation / 2.0, right.y, max_shift_mm)
    return changed


def apply_layout_plan(
    plan: LayoutPlan,
    circuit: Circuit,
    schematic: Schematic,
    *,
    max_shift_mm: float = _MAX_SHIFT_MM,
) -> LayoutExecution:
    """Execute validated geometry actions and rederive connectivity geometry."""
    symbols = _symbols_by_ref(schematic)
    circuit_before = circuit.model_dump_json()
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    changed = False

    for action in plan.actions[:_MAX_ACTIONS]:
        errors = validate_layout_action(action, circuit, schematic)
        if errors:
            rejected.append({"action": action.model_dump(mode="json"), "errors": errors})
            continue
        action_changed = False
        if action.type in {LayoutActionType.MOVE_NEAR, LayoutActionType.MOVE_GROUP}:
            action_changed = _move_near(action, symbols, max_shift_mm)
        elif action.type == LayoutActionType.ALIGN:
            action_changed = _align(action, symbols, max_shift_mm)
        elif action.type == LayoutActionType.DISTRIBUTE:
            action_changed = _distribute(action, symbols, max_shift_mm)
        elif action.type == LayoutActionType.COMPACT_BLOCK:
            action_changed = _compact_block(action, symbols, max_shift_mm)
        elif action.type == LayoutActionType.SEPARATE_BLOCKS:
            action_changed = _separate_blocks(action, symbols, max_shift_mm)
        changed |= action_changed
        applied.append({"action": action.model_dump(mode="json"), "changed": action_changed})

    unresolved = _reroute(circuit, schematic) if changed else []
    if circuit.model_dump_json() != circuit_before:
        raise RuntimeError("layout action executor modified Circuit IR")
    return LayoutExecution(
        changed=changed,
        applied=applied,
        rejected=rejected,
        unresolved=unresolved,
    )


def plan_visual_actions(review: dict[str, Any], circuit: Circuit) -> LayoutPlan:
    """Translate reviewer findings into a bounded typed action plan."""
    allowed_refs = set(circuit.components)
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        findings = []
    actions: list[LayoutAction] = []
    seen: set[tuple[Any, ...]] = set()

    def add(action: LayoutAction | None) -> None:
        if action is None or len(actions) >= _MAX_ACTIONS:
            return
        key = (
            action.type.value,
            tuple(action.refs),
            action.target,
            action.axis.value if action.axis else None,
            action.side.value,
        )
        if key not in seen:
            seen.add(key)
            actions.append(action)

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        explicit = normalize_layout_action(finding.get("action"), allowed_refs)
        if explicit is not None:
            add(explicit)
            continue
        refs_raw = finding.get("refs", [])
        refs = [str(ref) for ref in refs_raw if str(ref) in allowed_refs] if isinstance(refs_raw, list) else []
        code = str(finding.get("code", "")).upper()
        confidence = float(finding.get("confidence", 1.0) or 1.0)
        rationale = str(finding.get("message", ""))[:500]
        try:
            if code in {"SYMBOL_OVERLAP", "SYMBOL_SPACING"} and len(refs) >= 2:
                add(
                    LayoutAction(
                        type=LayoutActionType.SEPARATE_BLOCKS,
                        refs=refs[:2],
                        distance_mm=10.16,
                        confidence=confidence,
                        rationale=rationale,
                    )
                )
            elif "DECOUP" in code and len(refs) >= 2:
                add(
                    LayoutAction(
                        type=LayoutActionType.MOVE_NEAR,
                        refs=[refs[0]],
                        target=refs[1],
                        distance_mm=5.08,
                        confidence=confidence,
                        rationale=rationale,
                    )
                )
            elif ("GROUP" in code or "DENSITY" in code) and len(refs) >= 2:
                add(
                    LayoutAction(
                        type=LayoutActionType.COMPACT_BLOCK,
                        refs=refs,
                        spacing_mm=7.62,
                        confidence=confidence,
                        rationale=rationale,
                    )
                )
        except ValueError:
            continue

    return LayoutPlan(
        summary=f"{len(actions)} bounded geometry action(s) planned from visual findings",
        source="multimodal+deterministic",
        actions=actions,
    )


def _pipeline_scores(pipeline: dict[str, Any]) -> tuple[float, float]:
    visual = pipeline.get("visual_review", {})
    review = visual.get("review", {}) if isinstance(visual, dict) else {}
    combined = float(review.get("score", 0.0)) if isinstance(review, dict) else 0.0
    deterministic = (
        float(review.get("deterministic_score", combined)) if isinstance(review, dict) else combined
    )
    return deterministic, combined


def _erc_signatures(pipeline: dict[str, Any]) -> set[tuple[str, str]]:
    external = pipeline.get("kicad", {})
    if not isinstance(external, dict) or not external.get("available"):
        return set()
    violations = external.get("violations", [])
    if not isinstance(violations, list):
        return set()
    return {
        (str(item.get("severity", "")), str(item.get("description", "")))
        for item in violations
        if isinstance(item, dict)
    }


def _evaluate_current_geometry(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None,
    *,
    target_score: float,
    run_external: bool,
    settings: VisualAISettings | None,
    reviewer: MultimodalReviewer | None,
) -> dict[str, Any]:
    review = review_schematic_visual(
        schematic,
        circuit=circuit,
        resolver=resolver,
        run_render=run_external,
    )
    external = (
        run_kicad_erc(schematic, resolver=resolver)
        if run_external
        else {"available": False, "blocking": False, "violations": [], "error": "disabled"}
    )
    visual = {
        "target_score": target_score,
        "target_met": float(review["score"]) >= target_score,
        "changed": False,
        "attempts": [],
        "blocking": bool(review["blocking"]),
        "review": review,
    }
    pipeline: dict[str, Any] = {
        "kicad": external,
        "visual_review": visual,
        "blocking": bool(review["blocking"] or external.get("blocking")),
    }
    return apply_multimodal_review(
        pipeline,
        circuit,
        schematic,
        resolver=resolver,
        settings=settings,
        reviewer=reviewer,
    )


def _copy_geometry(source: Schematic, target: Schematic) -> None:
    source_by_ref = {symbol.reference: symbol for symbol in source.symbols}
    for symbol in target.symbols:
        chosen = source_by_ref[symbol.reference]
        symbol.x, symbol.y, symbol.rotation = chosen.x, chosen.y, chosen.rotation
    target.wires = [item.model_copy(deep=True) for item in source.wires]
    target.labels = [item.model_copy(deep=True) for item in source.labels]
    target.junctions = [item.model_copy(deep=True) for item in source.junctions]


def compare_visual_candidate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    circuit_unchanged: bool,
    changed: bool,
    unresolved: list[str],
) -> dict[str, Any]:
    """Apply the Phase-5 acceptance gates to one candidate."""
    base_det, base_score = _pipeline_scores(baseline)
    cand_det, cand_score = _pipeline_scores(candidate)
    new_erc = sorted(_erc_signatures(candidate) - _erc_signatures(baseline))
    reasons: list[str] = []
    if not changed:
        reasons.append("candidate made no geometry change")
    if unresolved:
        reasons.append("candidate has unresolved pin geometry")
    if not circuit_unchanged:
        reasons.append("Circuit IR changed")
    if new_erc:
        reasons.append("candidate introduced new ERC violations")
    if cand_det + 1e-6 < base_det:
        reasons.append("deterministic visual score regressed")
    if cand_score <= base_score + 0.05:
        reasons.append("combined visual score did not improve")
    external = candidate.get("kicad", {})
    base_external = baseline.get("kicad", {})
    if (
        isinstance(external, dict)
        and isinstance(base_external, dict)
        and external.get("blocking")
        and not base_external.get("blocking")
    ):
        reasons.append("candidate introduced a blocking ERC state")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "baseline_score": round(base_score, 1),
        "candidate_score": round(cand_score, 1),
        "baseline_deterministic_score": round(base_det, 1),
        "candidate_deterministic_score": round(cand_det, 1),
        "new_erc_violations": [list(item) for item in new_erc],
    }


def autofix_visual_layout(
    circuit: Circuit,
    schematic: Schematic,
    resolver: SymbolResolver | None = None,
    *,
    target_score: float = _DEFAULT_TARGET_SCORE,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    run_external: bool = True,
    settings: VisualAISettings | None = None,
    reviewer: MultimodalReviewer | None = None,
) -> dict[str, Any]:
    """Review -> plan -> execute -> verify -> accept/rollback, bounded to three passes."""
    if max_iterations < 1 or max_iterations > _DEFAULT_MAX_ITERATIONS:
        raise ValueError(f"max_iterations must be between 1 and {_DEFAULT_MAX_ITERATIONS}")
    target_score = max(0.0, min(100.0, target_score))
    circuit_before = circuit.model_dump_json()

    baseline = evaluate_visual_schematic(
        circuit,
        schematic,
        resolver=resolver,
        target_score=target_score,
        max_passes=4,
        run_external=run_external,
    )
    current = apply_multimodal_review(
        baseline,
        circuit,
        schematic,
        resolver=resolver,
        settings=settings,
        reviewer=reviewer,
    )
    iterations: list[dict[str, Any]] = []

    for index in range(1, max_iterations + 1):
        _, current_score = _pipeline_scores(current)
        if current_score >= target_score and not bool(current.get("blocking")):
            break
        visual = current.get("visual_review", {})
        review = visual.get("review", {}) if isinstance(visual, dict) else {}
        plan = plan_visual_actions(review if isinstance(review, dict) else {}, circuit)
        if not plan.actions:
            iterations.append(
                {
                    "iteration": index,
                    "accepted": False,
                    "stop_reason": "no safe layout actions could be planned",
                    "plan": plan.model_dump(mode="json"),
                }
            )
            break

        candidate = schematic.model_copy(deep=True)
        execution = apply_layout_plan(plan, circuit, candidate)
        candidate_pipeline = _evaluate_current_geometry(
            circuit,
            candidate,
            resolver,
            target_score=target_score,
            run_external=run_external,
            settings=settings,
            reviewer=reviewer,
        )
        decision = compare_visual_candidate(
            current,
            candidate_pipeline,
            circuit_unchanged=circuit.model_dump_json() == circuit_before,
            changed=execution.changed,
            unresolved=execution.unresolved,
        )
        iterations.append(
            {
                "iteration": index,
                "plan": plan.model_dump(mode="json"),
                "execution": execution.model_dump(mode="json"),
                **decision,
            }
        )
        if not decision["accepted"]:
            break
        _copy_geometry(candidate, schematic)
        current = candidate_pipeline

    if circuit.model_dump_json() != circuit_before:
        raise RuntimeError("visual auto-fix modified Circuit IR")
    _, final_score = _pipeline_scores(current)
    return {
        "target_score": target_score,
        "target_met": final_score >= target_score and not bool(current.get("blocking")),
        "iterations": iterations,
        "accepted_iterations": sum(1 for item in iterations if item.get("accepted")),
        "final_score": round(final_score, 1),
        "blocking": bool(current.get("blocking")),
        "pipeline": current,
    }

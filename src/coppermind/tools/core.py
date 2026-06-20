"""The Phase-0 core tool set (7 tools).

Naming follows the `resource_action` convention from the architecture doc so the
set stays searchable as it grows. Each function takes the Session first and
returns a plain dict (MCP-friendly, JSON-serializable). Mutating tools write to
the active transaction's working copy — nothing is persisted until
`design_commit`.
"""

from __future__ import annotations

from coppermind.domain import operations as ops
from coppermind.domain.models import Layer
from coppermind.intelligence.critique import critique as run_critique
from coppermind.session import Session
from coppermind.transactions.manager import Document


def project_create(session: Session, name: str, width_mm: float, height_mm: float) -> dict:
    """Create a new project with a rectangular board outline."""
    board = ops.create_board(name, width_mm, height_mm)
    session.backend.apply(board)
    session.document = Document(board, session.backend)
    return {"ok": True, "project": name, "board": f"{width_mm}x{height_mm}mm"}


def component_place(
    session: Session,
    reference: str,
    footprint: str,
    x_mm: float,
    y_mm: float,
    value: str = "",
    rotation: float = 0.0,
    layer: str = "F.Cu",
) -> dict:
    """Place a component on the working copy (uncommitted)."""
    doc = session.require_document()
    ops.add_component(
        doc.working(), reference, footprint, x_mm, y_mm, value, rotation, Layer(layer)
    )
    return {"ok": True, "placed": reference, "pending_commit": True}


def net_create(session: Session, name: str) -> dict:
    """Create an electrical net on the working copy (uncommitted)."""
    doc = session.require_document()
    ops.create_net(doc.working(), name)
    return {"ok": True, "net": name, "pending_commit": True}


def net_route(
    session: Session,
    net: str,
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    width_mm: float = 0.25,
    layer: str = "F.Cu",
) -> dict:
    """Route a copper trace segment on the working copy (uncommitted)."""
    doc = session.require_document()
    ops.route_track(
        doc.working(), net, (x1_mm, y1_mm), (x2_mm, y2_mm), width_mm, Layer(layer)
    )
    return {"ok": True, "routed_net": net, "pending_commit": True}


def design_preview(session: Session) -> dict:
    """Preview pending changes: structured diff, verification report, render.

    This is the safety surface — see what will change, what rules fire (including
    native KiCAD DRC), and a render of the result, all *before* committing.
    """
    doc = session.require_document()
    diff, violations = doc.preview()
    working = doc.working()
    render = session.backend.render(working)
    advice = run_critique(working)
    return {
        "diff": diff.summary(),
        "diff_detail": diff.model_dump(),
        "violations": [v.model_dump() for v in violations],
        "would_block": any(v.severity >= 30 for v in violations),
        "advice": [v.model_dump() for v in advice],
        "render_svg": render.decode("utf-8") if render else None,
    }


def design_commit(session: Session) -> dict:
    """Verify and commit pending changes. Blocked by ERROR-level violations."""
    doc = session.require_document()
    result = doc.commit()
    return {
        "committed": result.committed,
        "summary": result.summary(),
        "violations": [v.model_dump() for v in result.violations],
    }


def design_rollback(session: Session) -> dict:
    """Discard all pending (uncommitted) changes."""
    doc = session.require_document()
    doc.rollback()
    return {"ok": True, "rolled_back": True}


CORE_TOOLS = (
    project_create,
    component_place,
    net_create,
    net_route,
    design_preview,
    design_commit,
    design_rollback,
)

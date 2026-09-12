"""Always-visible high-frequency tools.

The primary agent surface is semantic: components, real symbol pins and nets.
Coordinate-level PCB operations remain implemented for compatibility, but are
routed on demand instead of occupying the LLM's default context.
"""

from __future__ import annotations

from coppermind.circuit import Circuit
from coppermind.domain import operations as ops
from coppermind.domain.models import Layer
from coppermind.intelligence.critique import critique as run_critique
from coppermind.schematic.models import Schematic
from coppermind.session import Session
from coppermind.tools.circuit import CIRCUIT_TOOLS
from coppermind.transactions.manager import Document


def project_create(session: Session, name: str, width_mm: float, height_mm: float) -> dict:
    """Create a project and initialize its board, schematic and semantic Circuit IR."""
    board = ops.create_board(name, width_mm, height_mm)
    session.backend.apply(board)
    session.document = Document(board, session.backend)
    session.schematic = Schematic(name=name)
    session.circuit = Circuit(name=name)
    session.commit_semantic_state()
    return {
        "ok": True,
        "project": name,
        "board": f"{width_mm}x{height_mm}mm",
        "circuit_ir": True,
        "schematic": True,
    }


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
    """Legacy: place a PCB component by coordinates (routed compatibility tool)."""
    doc = session.require_document()
    ops.add_component(
        doc.working(), reference, footprint, x_mm, y_mm, value, rotation, Layer(layer)
    )
    return {"ok": True, "placed": reference, "pending_commit": True}


def net_create(session: Session, name: str) -> dict:
    """Legacy: create a PCB-domain net directly (routed compatibility tool)."""
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
    """Legacy: route one PCB trace segment by coordinates (routed compatibility tool)."""
    doc = session.require_document()
    ops.route_track(
        doc.working(), net, (x1_mm, y1_mm), (x2_mm, y2_mm), width_mm, Layer(layer)
    )
    return {"ok": True, "routed_net": net, "pending_commit": True}


def design_preview(session: Session) -> dict:
    """Preview pending PCB and semantic Circuit IR changes before commit."""
    doc = session.require_document()
    diff, violations = doc.preview()
    working = doc.working()
    render = session.backend.render(working)
    advice = run_critique(working)
    circuit = session.circuit
    return {
        "diff": diff.summary(),
        "diff_detail": diff.model_dump(),
        "violations": [v.model_dump() for v in violations],
        "would_block": any(v.severity >= 30 for v in violations),
        "advice": [v.model_dump() for v in advice],
        "render_svg": render.decode("utf-8") if render else None,
        "semantic_dirty": session.semantic_dirty(),
        "circuit": circuit.model_dump(mode="json") if circuit is not None else None,
    }


def design_commit(session: Session) -> dict:
    """Verify and commit PCB plus semantic Circuit IR changes."""
    doc = session.require_document()
    result = doc.commit()
    if result.committed:
        session.commit_semantic_state()
    return {
        "committed": result.committed,
        "summary": result.summary(),
        "semantic_committed": result.committed and not session.semantic_dirty(),
        "violations": [v.model_dump() for v in result.violations],
    }


def design_rollback(session: Session) -> dict:
    """Discard pending PCB and semantic Circuit IR changes."""
    doc = session.require_document()
    doc.rollback()
    session.rollback_semantic_state()
    return {"ok": True, "rolled_back": True, "semantic_dirty": session.semantic_dirty()}


CORE_TOOLS = (
    project_create,
    *CIRCUIT_TOOLS,
    design_preview,
    design_commit,
    design_rollback,
)

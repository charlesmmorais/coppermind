"""Routed (long-tail) tools — discoverable on demand, not always visible.

Lower-frequency operations, including the Phase-3 design-intelligence tools.
They are NOT loaded into context up front; the model finds them via the
discovery tools and runs them through ``execute_tool``.
"""

from __future__ import annotations

from coppermind.domain import operations as ops
from coppermind.domain.netlist import component_netlist, pin_netlist
from coppermind.intelligence.placement import hpwl, suggest_placement
from coppermind.intelligence import blocks, knowledge
from coppermind.intelligence.critique import critique as run_critique
from coppermind.intelligence.explain import explain_board
from coppermind.integrations.autorouter import FreeroutingRunner
from coppermind.integrations.datasheets import enrich_bom
from coppermind.integrations.freerouting import apply_route_to_board, autoroute_dsn, parse_ses
from coppermind.safety import validate_input_file, validate_output_path
from coppermind.integrations.suppliers.optimize import effective_total, pick_cheapest
from coppermind.session import Session
from coppermind.variants import ComponentOverride, Variant, resolve_variant


# -- editing ---------------------------------------------------------------

def component_move(session: Session, reference: str, x_mm: float, y_mm: float) -> dict:
    """Move an existing component to a new position (uncommitted)."""
    doc = session.require_document()
    ops.move_component(doc.working(), reference, x_mm, y_mm)
    return {"ok": True, "moved": reference, "pending_commit": True}


def component_edit(
    session: Session,
    reference: str,
    value: str | None = None,
    footprint: str | None = None,
    rotation: float | None = None,
) -> dict:
    """Edit a component's value, footprint, or rotation (uncommitted)."""
    doc = session.require_document()
    ops.edit_component(doc.working(), reference, value=value, footprint=footprint, rotation=rotation)
    return {"ok": True, "edited": reference, "pending_commit": True}


def component_delete(session: Session, reference: str) -> dict:
    """Delete a component from the board (uncommitted)."""
    doc = session.require_document()
    ops.delete_component(doc.working(), reference)
    return {"ok": True, "deleted": reference, "pending_commit": True}


def component_list(session: Session) -> dict:
    """List all components on the working board."""
    board = session.require_document().working()
    return {
        "components": [
            {"reference": c.reference, "value": c.value, "footprint": c.footprint,
             "x": c.position.x, "y": c.position.y, "layer": c.layer.value}
            for c in board.components.values()
        ]
    }


def net_list(session: Session) -> dict:
    """List all electrical nets on the working board."""
    board = session.require_document().working()
    return {"nets": sorted(board.nets)}


def board_info(session: Session) -> dict:
    """Report board name, outline size, and item counts."""
    board = session.require_document().working()
    outline = board.outline
    return {
        "name": board.name,
        "size_mm": f"{outline.width}x{outline.height}" if outline else None,
        "components": len(board.components),
        "nets": len(board.nets),
        "tracks": len(board.tracks),
    }


def design_undo(session: Session) -> dict:
    """Undo the last committed change."""
    ok = session.require_document().undo()
    return {"ok": ok, "undone": ok}


def design_redo(session: Session) -> dict:
    """Redo the last undone change."""
    ok = session.require_document().redo()
    return {"ok": ok, "redone": ok}


def design_render(session: Session) -> dict:
    """Render the current working board as SVG."""
    doc = session.require_document()
    data = session.backend.render(doc.working())
    return {"render_svg": data.decode("utf-8") if data else None}


# -- design intelligence (Phase 3) -----------------------------------------

def design_critique(session: Session, assumed_current_a: float = 0.5) -> dict:
    """Proactively critique the working board against the EE knowledge base."""
    board = session.require_document().working()
    findings = run_critique(board, assumed_current_a=assumed_current_a)
    return {
        "kb_version": knowledge.KNOWLEDGE_BASE_VERSION,
        "findings": [v.model_dump() for v in findings],
    }


def design_list_rules(session: Session) -> dict:
    """List the EE knowledge-base rules with their citations."""
    return {
        "kb_version": knowledge.KNOWLEDGE_BASE_VERSION,
        "rules": [
            {"id": r.id, "title": r.title, "category": r.category.value, "citation": r.citation}
            for r in knowledge.all_rules()
        ],
    }


def design_explain_rule(session: Session, rule_id: str) -> dict:
    """Explain a single EE rule (statement, citation, rationale)."""
    return knowledge.get_rule(rule_id).model_dump()


def design_add_decoupling(
    session: Session, ic_reference: str, cap_reference: str, value: str = "100nF"
) -> dict:
    """Add a decoupling capacitor next to an IC (design block, uncommitted)."""
    doc = session.require_document()
    result = blocks.add_decoupling(doc.working(), ic_reference, cap_reference, value=value)
    return {"ok": True, "block": result.model_dump(), "pending_commit": True}


def design_add_led(
    session: Session,
    led_reference: str,
    resistor_reference: str,
    signal_net: str,
    x_mm: float,
    y_mm: float,
    resistor_value: str = "330",
) -> dict:
    """Add an LED indicator (LED + series resistor + net) design block (uncommitted)."""
    doc = session.require_document()
    result = blocks.add_led_indicator(
        doc.working(), led_reference, resistor_reference, signal_net, x_mm, y_mm,
        resistor_value=resistor_value,
    )
    return {"ok": True, "block": result.model_dump(), "pending_commit": True}


# -- collaboration & integrations (Phase 4) --------------------------------

def design_timeline(session: Session) -> dict:
    """Show the versioned timeline of committed steps (audit log)."""
    doc = session.require_document()
    return {"timeline": [e.model_dump() for e in doc.timeline()]}


def design_explain(session: Session) -> dict:
    """Explain the current board in plain language, with cited design advice."""
    board = session.require_document().working()
    return explain_board(board)


def supplier_search(
    session: Session, query: str, package: str | None = None, basic_only: bool = False
) -> dict:
    """Search the supplier catalog for parts."""
    parts = session.supplier.search(query, package=package, basic_only=basic_only)
    return {"provider": session.supplier.name, "parts": [p.model_dump() for p in parts]}


def supplier_part(session: Session, part_id: str) -> dict:
    """Get full details (pricing, stock) for one supplier part."""
    part = session.supplier.get(part_id)
    return {"part": part.model_dump() if part else None}


def supplier_alternatives(session: Session, part_id: str) -> dict:
    """Suggest alternative parts for a given part id."""
    alts = session.supplier.alternatives(part_id)
    return {"alternatives": [p.model_dump() for p in alts]}


def supplier_cheapest(
    session: Session, query: str, qty: int = 100, basic_only: bool = False
) -> dict:
    """Find the cheapest in-stock part for a query at a quantity (Basic-fee aware)."""
    parts = session.supplier.search(query, basic_only=basic_only)
    best = pick_cheapest(parts, qty)
    return {
        "qty": qty,
        "cheapest": best.model_dump() if best else None,
        "effective_total_usd": round(effective_total(best, qty), 4) if best else None,
    }


def route_check(session: Session, jar_path: str = "~/.kicad-mcp/freerouting.jar") -> dict:
    """Check whether the Freerouting autorouter is ready (runtime + jar)."""
    import os

    runner = FreeroutingRunner(os.path.expanduser(jar_path))
    return runner.check()


# -- variants & layout (Phase 5) -------------------------------------------

def variant_preview(session: Session, overrides: dict) -> dict:
    """Preview a design variant over the current board (non-mutating).

    `overrides` maps reference -> {value?, footprint?, dnp?}.
    """
    board = session.require_document().working()
    variant = Variant(
        name="preview",
        overrides={r: ComponentOverride(**o) for r, o in overrides.items()},
    )
    resolved = resolve_variant(board, variant)
    return {
        "components": [
            {"reference": c.reference, "value": c.value, "footprint": c.footprint}
            for c in resolved.components.values()
        ]
    }


def variant_apply(session: Session, overrides: dict) -> dict:
    """Apply a variant to the working board (DNP removes, else edits; uncommitted)."""
    board = session.require_document().working()
    applied = []
    for ref, o in overrides.items():
        if ref not in board.components:
            continue
        if o.get("dnp"):
            ops.delete_component(board, ref)
            applied.append(f"{ref}:DNP")
        else:
            ops.edit_component(board, ref, value=o.get("value"), footprint=o.get("footprint"))
            applied.append(ref)
    return {"ok": True, "applied": applied, "pending_commit": True}


def design_placement_report(session: Session) -> dict:
    """Report placement metrics: component count, bounding box, total track length."""
    board = session.require_document().working()
    comps = list(board.components.values())
    xs = [c.position.x for c in comps]
    ys = [c.position.y for c in comps]
    bbox = {"w": (max(xs) - min(xs)) if xs else 0.0, "h": (max(ys) - min(ys)) if ys else 0.0}
    track_len = sum(t.start.distance_to(t.end) for t in board.tracks)
    return {"components": len(comps), "bbox_mm": bbox, "total_track_length_mm": round(track_len, 3)}


# -- autorouting (Freerouting) ---------------------------------------------

def route_import_ses(session: Session, ses_path: str, replace: bool = True) -> dict:
    """Import a Freerouting .ses session into the working board (uncommitted)."""
    doc = session.require_document()
    board = doc.working()
    ses_path = validate_input_file(ses_path, {".ses"})
    with open(ses_path, encoding="utf-8") as fh:
        result = parse_ses(fh.read())
    applied = apply_route_to_board(board, result, replace_routing=replace)
    board.tracks = applied.tracks
    board.vias = applied.vias
    return {
        "ok": True,
        "tracks": len(result.tracks),
        "vias": len(result.vias),
        "pending_commit": True,
    }


def route_autoroute(
    session: Session,
    dsn_path: str,
    ses_path: str,
    jar_path: str = "~/.kicad-mcp/freerouting.jar",
    max_passes: int = 10,
) -> dict:
    """Run Freerouting on a Specctra .dsn and import the routed result (uncommitted).

    Requires Java 21+ or Docker/Podman and the freerouting jar (see route_check).
    """
    import os

    doc = session.require_document()
    dsn_path = validate_input_file(dsn_path, {".dsn"})
    jar_path = validate_input_file(os.path.expanduser(jar_path), {".jar"})
    ses_path = validate_output_path(ses_path, {".ses"})
    result = autoroute_dsn(dsn_path, ses_path, jar_path, max_passes)
    board = doc.working()
    applied = apply_route_to_board(board, result)
    board.tracks = applied.tracks
    board.vias = applied.vias
    return {"ok": True, "tracks": len(result.tracks), "vias": len(result.vias),
            "pending_commit": True}


def route_export_dsn(session: Session, dsn_path: str) -> dict:
    """Export the current board to Specctra .dsn for autorouting.

    kicad-cli cannot export DSN; this uses the live KiCAD IPC export action when
    available, otherwise it asks the user to export via File > Export > Specctra DSN.
    """
    backend = session.backend
    exporter = getattr(backend, "export_specctra_dsn", None)
    if callable(exporter):
        exporter(dsn_path)  # pragma: no cover - needs live KiCAD
        return {"ok": True, "dsn": dsn_path}
    return {
        "ok": False,
        "reason": "current backend cannot export DSN",
        "hint": "In KiCAD: File > Export > Specctra DSN, then use route_autoroute.",
    }


# -- datasheets (LCSC) -----------------------------------------------------

def datasheet_get(session: Session, part_id: str) -> dict:
    """Get the datasheet URL for an LCSC part id via the active supplier."""
    part = session.supplier.get(part_id)
    return {"part_id": part_id, "datasheet": part.datasheet if part else ""}


def datasheet_enrich(session: Session, bom: dict) -> dict:
    """Fill datasheet URLs for a BOM (reference -> LCSC id) via the supplier."""
    return {"datasheets": enrich_bom(bom, session.supplier)}


def component_add_pad(
    session: Session, reference: str, number: str, offset_x: float, offset_y: float,
    net: str = "", drill: float = 0.0,
) -> dict:
    """Add a pad/pin to a component (offset relative to its origin; uncommitted)."""
    doc = session.require_document()
    ops.add_pad(doc.working(), reference, number, offset_x, offset_y, net=net, drill=drill)
    return {"ok": True, "reference": reference, "pad": number, "pending_commit": True}


def component_pads(session: Session, reference: str) -> dict:
    """List a component's pads (number, offset, net)."""
    board = session.require_document().working()
    if reference not in board.components:
        raise ValueError(f"component '{reference}' does not exist")
    return {"reference": reference, "pads": [
        {"number": p.number, "offset": [p.offset.x, p.offset.y], "net": p.net}
        for p in board.components[reference].pads
    ]}


def design_netlist(session: Session) -> dict:
    """Pin-level netlist of the working board: net -> ['REF.PAD', ...]."""
    return {"netlist": pin_netlist(session.require_document().working())}


def design_suggest_placement(session: Session) -> dict:
    """Suggest component moves that reduce wirelength (HPWL), using the board netlist."""
    board = session.require_document().working()
    netlist = component_netlist(board)
    positions = {ref: (c.position.x, c.position.y) for ref, c in board.components.items()}
    moved = suggest_placement(positions, netlist)
    suggestions = {
        ref: {"x": round(pos[0], 3), "y": round(pos[1], 3)}
        for ref, pos in moved.items() if pos != positions[ref]
    }
    return {
        "hpwl_before": round(hpwl(positions, netlist), 3),
        "hpwl_after": round(hpwl(moved, netlist), 3),
        "suggested_moves": suggestions,
    }


ROUTED_TOOLS = (
    component_move,
    component_edit,
    component_delete,
    component_list,
    net_list,
    board_info,
    design_undo,
    design_redo,
    design_render,
    design_critique,
    design_list_rules,
    design_explain_rule,
    design_add_decoupling,
    design_add_led,
    design_timeline,
    design_explain,
    supplier_search,
    supplier_part,
    supplier_alternatives,
    supplier_cheapest,
    route_check,
    variant_preview,
    variant_apply,
    design_placement_report,
    route_import_ses,
    route_autoroute,
    route_export_dsn,
    datasheet_get,
    datasheet_enrich,
    component_add_pad,
    component_pads,
    design_netlist,
    design_suggest_placement,
)

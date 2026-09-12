"""High-level agent tools backed by the semantic Circuit IR.

These are the preferred authoring surface for an LLM. The model names real
components, pins and nets; geometric placement/wiring is an implementation
detail owned by the composer or the incremental schematic engine rather than
prompt context.
"""

from __future__ import annotations

from coppermind.circuit import Component, Net, Pin, PinRef
from coppermind.libraries.catalog import find_symbols
from coppermind.schematic.incremental import (
    export_incremental_schematic,
    place_relative_geometry,
    route_net_incremental,
    validate_incremental_schematic,
)
from coppermind.schematic.models import (
    SchLibraryDefinition,
    SchLibrarySymbol,
    SchSymbol,
)
from coppermind.session import Session


def _cache_library_symbol(session: Session, lib_id: str) -> SchLibrarySymbol:
    sch = session.require_schematic()
    cached = sch.library_symbols.get(lib_id)
    if cached is not None:
        return cached
    resolved = session.symbol_resolver.resolve(lib_id)
    cached = SchLibrarySymbol(
        lib_id=resolved.lib_id,
        source_path=resolved.source_path,
        pins=resolved.pins,
        definitions=[
            SchLibraryDefinition(lib_id=d.lib_id, raw_s_expression=d.raw_s_expression)
            for d in resolved.definitions
        ],
    )
    sch.library_symbols[lib_id] = cached
    return cached


def _automatic_symbol_position(index: int) -> tuple[float, float]:
    """Deterministic temporary position until the agent places the component."""
    columns = 4
    x = 25.4 + (index % columns) * 38.1
    y = 25.4 + (index // columns) * 30.48
    return x, y


def _pins_for_instance(resolved, unit: int) -> dict[str, Pin]:
    """Select pins for one displayed unit, including KiCad common unit 0."""
    selected: dict[str, Pin] = {}
    for pin in resolved.pins:
        if pin.unit not in (0, unit):
            continue
        current = selected.get(pin.number)
        if current is None or (current.unit == 0 and pin.unit == unit):
            selected[pin.number] = pin
    return selected


def component_add(
    session: Session,
    reference: str,
    symbol: str,
    value: str = "",
    footprint: str = "",
    unit: int = 1,
) -> dict:
    """Add a component from a real KiCad symbol; no coordinates are required."""
    circuit = session.require_circuit()
    sch = session.require_schematic()
    if reference in circuit.components or any(s.reference == reference for s in sch.symbols):
        raise ValueError(f"component '{reference}' already exists")

    resolved = session.symbol_resolver.resolve(symbol)
    explicit_units = sorted({pin.unit for pin in resolved.pins if pin.unit > 0})
    available_units = explicit_units or [1]
    if unit not in available_units:
        raise ValueError(
            f"symbol '{symbol}' has units {available_units}; requested unit {unit} is not available"
        )

    pins = _pins_for_instance(resolved, unit)
    if not pins:
        raise ValueError(f"symbol '{symbol}' has no pins available for unit {unit}")

    component = Component(
        reference=reference,
        symbol_id=resolved.lib_id,
        value=value,
        footprint=footprint,
        pins=pins,
        properties={"unit": str(unit)},
    )
    circuit.add_component(component)
    _cache_library_symbol(session, resolved.lib_id)

    x, y = _automatic_symbol_position(len(sch.symbols))
    sch.symbols.append(
        SchSymbol(
            lib_id=resolved.lib_id,
            reference=reference,
            value=value,
            x=x,
            y=y,
            unit=unit,
        )
    )
    return {
        "ok": True,
        "reference": reference,
        "symbol": resolved.lib_id,
        "unit": unit,
        "pins": [
            {
                "number": pin.number,
                "name": pin.name,
                "electrical_type": pin.electrical_type.value,
                "unit": pin.unit,
            }
            for pin in pins.values()
        ],
        "pending_commit": True,
    }


def create_net(session: Session, name: str, net_class: str | None = None) -> dict:
    """Create a named semantic net in the Circuit IR."""
    circuit = session.require_circuit()
    if name in circuit.nets:
        raise ValueError(f"net '{name}' already exists")
    circuit.nets[name] = Net(name=name, net_class=net_class)
    return {"ok": True, "net": name, "net_class": net_class, "pending_commit": True}


def _parse_pin_ref(value: str) -> tuple[str, str]:
    reference, sep, pin = value.rpartition(".")
    if not sep or not reference or not pin:
        raise ValueError(f"invalid pin reference '{value}'; expected 'REF.PIN'")
    return reference, pin


def connect_pins(session: Session, net: str, pins: list[str]) -> dict:
    """Connect semantic pins such as ['U1.3', 'R1.1'] to an existing net."""
    circuit = session.require_circuit()
    if net not in circuit.nets:
        raise KeyError(f"net '{net}' does not exist; call create_net first")
    if len(pins) < 2:
        raise ValueError("connect_pins requires at least two pins")

    refs: list[PinRef] = []
    requested_keys: set[str] = set()
    for value in pins:
        reference, selector = _parse_pin_ref(value)
        component = circuit.components.get(reference)
        if component is None:
            raise KeyError(f"component '{reference}' does not exist")
        resolved_pin = component.pin(selector)
        ref = PinRef(component=reference, pin=resolved_pin.number)
        if ref.key() in requested_keys:
            continue
        requested_keys.add(ref.key())
        refs.append(ref)

    if len(refs) < 2:
        raise ValueError("connect_pins requires at least two distinct pins")

    for other_name, other_net in circuit.nets.items():
        if other_name == net:
            continue
        occupied = {node.key() for node in other_net.nodes}
        conflict = occupied.intersection(ref.key() for ref in refs)
        if conflict:
            pin = sorted(conflict)[0]
            raise ValueError(f"pin '{pin}' is already connected to net '{other_name}'")

    circuit.connect(net, *refs)
    return {
        "ok": True,
        "net": net,
        "pins": [ref.key() for ref in circuit.nets[net].nodes],
        "pending_commit": True,
    }


def component_place_relative(
    session: Session,
    reference: str,
    anchor: str,
    direction: str = "right",
    gap_mm: float = 25.4,
    lock: bool = True,
) -> dict:
    """Place a component relative to an existing symbol without absolute coordinates."""
    circuit = session.require_circuit()
    if reference not in circuit.components:
        raise KeyError(f"component '{reference}' does not exist")
    if anchor not in circuit.components:
        raise KeyError(f"anchor component '{anchor}' does not exist")

    placement = place_relative_geometry(
        session.require_schematic(),
        reference,
        anchor,
        direction=direction,
        gap_mm=gap_mm,
    )
    if lock:
        circuit.components[reference].properties["placement_locked"] = "true"
    return {
        "ok": True,
        **placement,
        "locked": lock,
        "pending_commit": True,
    }


def component_freeze_placement(session: Session, references: list[str] | None = None) -> dict:
    """Mark current component placements as stable for the incremental authoring loop."""
    circuit = session.require_circuit()
    selected = references or sorted(circuit.components)
    missing = [ref for ref in selected if ref not in circuit.components]
    if missing:
        raise KeyError(f"unknown components: {', '.join(sorted(missing))}")
    for ref in selected:
        circuit.components[ref].properties["placement_locked"] = "true"
    return {"ok": True, "references": selected, "pending_commit": True}


def connect_incremental(session: Session, net: str, pins: list[str]) -> dict:
    """Connect pins in Circuit IR and reroute only that changed net."""
    circuit = session.require_circuit()
    if net not in circuit.nets:
        raise KeyError(f"net '{net}' does not exist; call create_net first")
    before = circuit.nets[net].model_copy(deep=True)
    try:
        connected = connect_pins(session, net, pins)
        route = route_net_incremental(circuit, session.require_schematic(), net)
    except Exception:
        circuit.nets[net] = before
        raise
    return {
        **connected,
        "incremental": True,
        "route": route,
    }


def schematic_checkpoint(session: Session, run_external: bool = True) -> dict:
    """Validate the current incremental drawing and snapshot it when non-blocking."""
    validation = validate_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        resolver=session.symbol_resolver,
        run_external=run_external,
    )
    committed = not bool(validation["blocking"])
    if committed:
        session.commit_semantic_state()
    return {
        "committed": committed,
        "semantic_committed": committed,
        "validation": validation,
        "semantic_dirty": session.semantic_dirty(),
    }


def schematic_export_current(
    session: Session,
    path: str,
    allow_invalid: bool = False,
    run_external: bool = True,
) -> dict:
    """Export current incremental geometry without running whole-sheet composition."""
    return export_incremental_schematic(
        session.require_circuit(),
        session.require_schematic(),
        path,
        resolver=session.symbol_resolver,
        allow_invalid=allow_invalid,
        run_external=run_external,
    )


def inspect_component(session: Session, reference: str) -> dict:
    """Inspect a Circuit IR component, its real pins and current net membership."""
    circuit = session.require_circuit()
    component = circuit.components.get(reference)
    if component is None:
        raise KeyError(f"component '{reference}' does not exist")

    pin_nets: dict[str, list[str]] = {number: [] for number in component.pins}
    for net_name, net in circuit.nets.items():
        for node in net.nodes:
            if node.component != reference:
                continue
            pin = component.pin(node.pin)
            pin_nets.setdefault(pin.number, []).append(net_name)

    return {
        "reference": component.reference,
        "symbol": component.symbol_id,
        "value": component.value,
        "footprint": component.footprint,
        "placement_locked": component.properties.get("placement_locked") == "true",
        "pins": [
            {
                "number": pin.number,
                "name": pin.name,
                "electrical_type": pin.electrical_type.value,
                "unit": pin.unit,
                "nets": sorted(pin_nets.get(pin.number, [])),
            }
            for pin in component.pins.values()
        ],
    }


def find_symbol(
    session: Session,
    query: str,
    library: str | None = None,
    limit: int = 20,
) -> dict:
    """Search installed/project KiCad libraries for real symbols."""
    matches = find_symbols(session.symbol_resolver, query, library=library, limit=limit)
    return {"query": query, "library": library, "matches": matches}


CIRCUIT_TOOLS = (
    component_add,
    connect_pins,
    create_net,
    inspect_component,
    find_symbol,
)

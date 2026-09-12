"""Pure writer: a Coppermind Schematic -> KiCad ``.kicad_sch`` text.

Library graphics and pins come from the user's real KiCad ``.kicad_sym`` files.
No generic two-pin fallback is generated.
"""

from __future__ import annotations

import uuid as _uuid

from coppermind.libraries import SymbolResolver
from coppermind.schematic.models import (
    SchLibraryDefinition,
    SchLibrarySymbol,
    Schematic,
)

_VERSION = "20231120"  # KiCad 8 format; KiCad 9/10 open and upgrade it.


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())


def _fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _uid() -> str:
    return str(_uuid.uuid4())


def _as_schematic_library(resolved) -> SchLibrarySymbol:
    return SchLibrarySymbol(
        lib_id=resolved.lib_id,
        source_path=resolved.source_path,
        pins=resolved.pins,
        definitions=[
            SchLibraryDefinition(lib_id=d.lib_id, raw_s_expression=d.raw_s_expression)
            for d in resolved.definitions
        ],
    )


def _resolved_library_symbols(
    sch: Schematic,
    resolver: SymbolResolver | None,
) -> dict[str, SchLibrarySymbol]:
    result = dict(sch.library_symbols)
    missing = {sym.lib_id for sym in sch.symbols} - set(result)
    if missing:
        active = resolver or SymbolResolver()
        for lib_id in sorted(missing):
            result[lib_id] = _as_schematic_library(active.resolve(lib_id))
    return result


def _symbol_instance(sym, project: str, library: SchLibrarySymbol) -> str:
    x, y, rot = _fmt(sym.x), _fmt(sym.y), _fmt(sym.rotation)
    lines: list[str] = []
    lines.append("(symbol")
    lines.append(f'  (lib_id "{sym.lib_id}")')
    lines.append(f"  (at {x} {y} {rot})")
    lines.append(f"  (unit {sym.unit})")
    lines.append("  (exclude_from_sim no)")
    lines.append("  (in_bom yes)")
    lines.append("  (on_board yes)")
    lines.append("  (dnp no)")
    lines.append(f'  (uuid "{sym.uuid}")')
    lines.append(
        f'  (property "Reference" "{sym.reference}" (at {x} {_fmt(sym.y - 2.54)} 0) '
        "(effects (font (size 1.27 1.27))))"
    )
    lines.append(
        f'  (property "Value" "{sym.value}" (at {x} {_fmt(sym.y + 2.54)} 0) '
        "(effects (font (size 1.27 1.27))))"
    )
    seen: set[str] = set()
    for pin in library.pins_for_unit(sym.unit):
        if pin.number in seen:
            continue
        seen.add(pin.number)
        lines.append(f'  (pin "{pin.number}" (uuid "{_uid()}"))')
    lines.append("  (instances")
    lines.append(f'    (project "{project}"')
    lines.append(f'      (path "/{sym.uuid}" (reference "{sym.reference}") (unit {sym.unit}))')
    lines.append("    )")
    lines.append("  )")
    lines.append(")")
    return "\n".join(lines)


def _wire(w) -> str:
    return (
        "(wire (pts "
        f"(xy {_fmt(w.x1)} {_fmt(w.y1)}) (xy {_fmt(w.x2)} {_fmt(w.y2)}))\n"
        "  (stroke (width 0) (type default))\n"
        f'  (uuid "{w.uuid}")\n'
        ")"
    )


def _junction(j) -> str:
    return (
        f"(junction (at {_fmt(j.x)} {_fmt(j.y)}) (diameter 0) (color 0 0 0 0)\n"
        f'  (uuid "{j.uuid}")\n'
        ")"
    )


def _label(label) -> str:
    return (
        f'(label "{label.text}" (at {_fmt(label.x)} {_fmt(label.y)} {_fmt(label.rotation)})\n'
        "  (effects (font (size 1.27 1.27)) (justify left bottom))\n"
        f'  (uuid "{label.uuid}")\n'
        ")"
    )


def schematic_to_kicad_sch(
    sch: Schematic,
    resolver: SymbolResolver | None = None,
) -> str:
    libraries = _resolved_library_symbols(sch, resolver)
    out: list[str] = []
    out.append("(kicad_sch")
    out.append(f"  (version {_VERSION})")
    out.append('  (generator "coppermind")')
    out.append('  (generator_version "0.2")')
    out.append(f'  (uuid "{sch.uuid}")')
    out.append(f'  (paper "{sch.paper}")')

    definitions: dict[str, str] = {}
    for lib_id in sorted({s.lib_id for s in sch.symbols}):
        for definition in libraries[lib_id].definitions:
            definitions.setdefault(definition.lib_id, definition.raw_s_expression)
    out.append("  (lib_symbols")
    for raw in definitions.values():
        out.append(_indent(raw, 4))
    out.append("  )")

    for w in sch.wires:
        out.append(_indent(_wire(w), 2))
    for j in sch.junctions:
        out.append(_indent(_junction(j), 2))
    for label in sch.labels:
        out.append(_indent(_label(label), 2))
    for sym in sch.symbols:
        out.append(_indent(_symbol_instance(sym, sch.name, libraries[sym.lib_id]), 2))

    out.append("  (sheet_instances")
    out.append('    (path "/" (page "1"))')
    out.append("  )")
    out.append(")")
    return "\n".join(out) + "\n"

"""Pure writer: a Coppermind Schematic -> KiCAD ``.kicad_sch`` text.

Mirrors the ``.kicad_pcb`` serializer: no KiCAD import, deterministic output. It
embeds every used symbol's definition in ``lib_symbols`` (see ``schematic.symbols``)
so the file is self-contained and opens in Eeschema. MVP scope: a flat sheet with
symbols, wires, net labels and junctions.
"""

from __future__ import annotations

import uuid as _uuid

from coppermind.schematic.models import Schematic
from coppermind.schematic.symbols import lib_symbol_def, pin_numbers

_VERSION = "20231120"  # KiCAD 8 schematic format; KiCAD 9/10 open and upgrade it.


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())


def _fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _uid() -> str:
    return str(_uuid.uuid4())


def _symbol_instance(sym, project: str) -> str:
    x, y, rot = _fmt(sym.x), _fmt(sym.y), _fmt(sym.rotation)
    lines: list[str] = []
    lines.append("(symbol")
    lines.append(f'  (lib_id "{sym.lib_id}")')
    lines.append(f"  (at {x} {y} {rot})")
    lines.append("  (unit 1)")
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
    for number in pin_numbers(sym.lib_id):
        lines.append(f'  (pin "{number}" (uuid "{_uid()}"))')
    lines.append("  (instances")
    lines.append(f'    (project "{project}"')
    lines.append(f'      (path "/{sym.uuid}" (reference "{sym.reference}") (unit 1))')
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


def schematic_to_kicad_sch(sch: Schematic) -> str:
    """Render a Schematic to ``.kicad_sch`` text."""
    out: list[str] = []
    out.append("(kicad_sch")
    out.append(f"  (version {_VERSION})")
    out.append('  (generator "coppermind")')
    out.append('  (generator_version "0.1")')
    out.append(f'  (uuid "{sch.uuid}")')
    out.append(f'  (paper "{sch.paper}")')

    out.append("  (lib_symbols")
    for lib_id in sorted({s.lib_id for s in sch.symbols}):
        out.append(_indent(lib_symbol_def(lib_id), 4))
    out.append("  )")

    for w in sch.wires:
        out.append(_indent(_wire(w), 2))
    for j in sch.junctions:
        out.append(_indent(_junction(j), 2))
    for label in sch.labels:
        out.append(_indent(_label(label), 2))
    for sym in sch.symbols:
        out.append(_indent(_symbol_instance(sym, sch.name), 2))

    out.append("  (sheet_instances")
    out.append('    (path "/" (page "1"))')
    out.append("  )")
    out.append(")")
    return "\n".join(out) + "\n"

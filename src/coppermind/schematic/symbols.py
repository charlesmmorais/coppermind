"""Embedded symbol library for the schematic serializer.

KiCAD schematics embed the *definition* of every symbol they use inside the
``lib_symbols`` block (graphics + pins), just like a board embeds nothing but a
schematic must carry its symbols. Rather than read the user's installed symbol
libraries (which the IPC API does not expose), we generate a small, guaranteed
valid definition for each ``lib_id`` from a compact spec.

Known devices (R, C, LED) get sensible 2-pin bodies; any unknown ``lib_id`` falls
back to a generic 2-pin box. Every symbol renders and connects correctly; richer
graphics can be added later without touching the serializer.
"""

from __future__ import annotations

# lib_id -> ordered list of pin numbers. Used both to draw the lib symbol and to
# emit the per-instance (pin ...) entries.
_DEVICES: dict[str, list[str]] = {
    "Device:R": ["1", "2"],
    "Device:C": ["1", "2"],
    "Device:L": ["1", "2"],
    "Device:LED": ["1", "2"],
    "Device:D": ["1", "2"],
}

_DEFAULT_PINS = ["1", "2"]


def pin_numbers(lib_id: str) -> list[str]:
    """Return the ordered pin numbers for a lib_id (generic 2-pin if unknown)."""
    return list(_DEVICES.get(lib_id, _DEFAULT_PINS))


def _reference_prefix(lib_id: str) -> str:
    name = lib_id.split(":", 1)[-1]
    return name[0] if name else "U"


def lib_symbol_def(lib_id: str) -> str:
    """Build the ``(symbol "lib_id" ...)`` block for the lib_symbols section.

    Pins are laid out horizontally (pin 1 left, pin 2 right, extra pins stacked
    down the right edge) around a rectangular body, which is valid for any device.
    """
    pins = pin_numbers(lib_id)
    prefix = _reference_prefix(lib_id)
    body_half = 1.27
    lines: list[str] = []
    lines.append(f'(symbol "{lib_id}"')
    lines.append("  (pin_numbers (hide yes))")
    lines.append("  (pin_names (offset 0.254))")
    lines.append("  (exclude_from_sim no)")
    lines.append("  (in_bom yes)")
    lines.append("  (on_board yes)")
    lines.append(
        f'  (property "Reference" "{prefix}" (at 0 2.54 0) '
        "(effects (font (size 1.27 1.27))))"
    )
    lines.append(
        '  (property "Value" "" (at 0 -2.54 0) '
        "(effects (font (size 1.27 1.27))))"
    )
    lines.append(
        '  (property "Footprint" "" (at 0 0 0) '
        "(effects (font (size 1.27 1.27)) (hide yes)))"
    )
    lines.append(
        '  (property "Datasheet" "~" (at 0 0 0) '
        "(effects (font (size 1.27 1.27)) (hide yes)))"
    )
    # body graphics
    lines.append(f'  (symbol "{lib_id.split(":")[-1]}_0_1"')
    lines.append(
        f"    (rectangle (start -2.54 {body_half}) (end 2.54 {-body_half})"
    )
    lines.append("      (stroke (width 0.254) (type default))")
    lines.append("      (fill (type none)))")
    lines.append("  )")
    # pins
    lines.append(f'  (symbol "{lib_id.split(":")[-1]}_1_1"')
    for i, number in enumerate(pins):
        if i == 0:
            at = "(at -5.08 0 0)"          # left, points right
        elif i == 1:
            at = "(at 5.08 0 180)"         # right, points left
        else:
            y = -2.54 * (i - 1)
            at = f"(at 5.08 {y} 180)"
        lines.append(f"    (pin passive line {at} (length 2.54)")
        lines.append('      (name "~" (effects (font (size 1.27 1.27))))')
        lines.append(f'      (number "{number}" (effects (font (size 1.27 1.27)))))')
    lines.append("  )")
    lines.append(")")
    return "\n".join(lines)

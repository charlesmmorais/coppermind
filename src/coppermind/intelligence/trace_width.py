"""IPC-2221 trace-width calculator.

Pure, citable, testable. Given a target current, computes the minimum copper
trace width for a chosen temperature rise and copper weight. This is the kind of
real engineering knowledge that turns a command translator into a copilot: every
recommendation can point back to the standard it came from.

IPC-2221 external/internal constants:
    A_mils2 = (I / (k * dT^0.44)) ^ (1 / 0.725)
    width   = A_mils2 / thickness_mils
with k = 0.048 (external layers) or 0.024 (internal layers), and
1 oz copper ≈ 1.378 mils thick.
"""

from __future__ import annotations

_MIL_TO_MM = 0.0254
_OZ_TO_MILS = 1.378


def min_trace_width_mm(
    current_a: float,
    temp_rise_c: float = 10.0,
    copper_oz: float = 1.0,
    external: bool = True,
) -> float:
    """Minimum trace width in mm to carry ``current_a`` per IPC-2221."""
    if current_a <= 0:
        return 0.0
    k = 0.048 if external else 0.024
    area_mils2 = (current_a / (k * (temp_rise_c**0.44))) ** (1.0 / 0.725)
    thickness_mils = _OZ_TO_MILS * copper_oz
    width_mils = area_mils2 / thickness_mils
    return width_mils * _MIL_TO_MM

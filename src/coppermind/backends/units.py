"""Unit conversion between Coppermind (mm) and KiCAD IPC (nanometres).

KiCAD's IPC API expresses all lengths as integer nanometres. Keeping the
conversion in one tiny, pure module means the IPC adapter never sprinkles magic
factors around, and the conversion itself is unit-tested.
"""

from __future__ import annotations

NM_PER_MM = 1_000_000


def mm_to_nm(mm: float) -> int:
    """Convert millimetres (float) to integer nanometres (KiCAD internal unit)."""
    return round(mm * NM_PER_MM)


def nm_to_mm(nm: int) -> float:
    """Convert integer nanometres to millimetres."""
    return nm / NM_PER_MM

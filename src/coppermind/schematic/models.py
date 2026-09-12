"""Schematic models.

Two layers live here:

* hierarchical netlist model (``Sheet``/``SchPin``/``SheetInstance``);
* drawable schematic model used by the KiCad file backend.

Unlike the old MVP, drawable symbols are backed by a resolved real KiCad
library definition. There is deliberately no synthetic/generic symbol model.
"""

from __future__ import annotations

import uuid as _uuid

from pydantic import BaseModel, Field

from coppermind.circuit import Pin


def _uid() -> str:
    return str(_uuid.uuid4())


class SchPin(BaseModel):
    symbol: str
    pin: str
    net: str


class SheetInstance(BaseModel):
    sheet: Sheet
    port_map: dict[str, str] = {}


class Sheet(BaseModel):
    name: str
    pins: list[SchPin] = []
    ports: list[str] = []
    subsheets: list[SheetInstance] = []


SheetInstance.model_rebuild()
Sheet.model_rebuild()


class SchLibraryDefinition(BaseModel):
    lib_id: str
    raw_s_expression: str


class SchLibrarySymbol(BaseModel):
    """Resolved library metadata cached with a schematic session."""

    lib_id: str
    source_path: str
    pins: list[Pin] = Field(default_factory=list)
    definitions: list[SchLibraryDefinition] = Field(default_factory=list)

    def pins_for_unit(self, unit: int) -> list[Pin]:
        """Return pins visible in a KiCad unit, including common unit-0 pins.

        KiCad uses unit ``0`` for geometry/pins shared by all displayed units.
        A drawable symbol instance is still placed as unit 1..N; unit 0 is not
        itself an instance selector.
        """
        selected: dict[str, Pin] = {}
        for pin in self.pins:
            if pin.unit not in (0, unit):
                continue
            current = selected.get(pin.number)
            if current is None or (current.unit == 0 and pin.unit == unit):
                selected[pin.number] = pin
        return list(selected.values())


class SchSymbol(BaseModel):
    """Placed symbol instance referencing a resolved KiCad library symbol."""

    lib_id: str
    reference: str
    value: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    unit: int = 1
    uuid: str = Field(default_factory=_uid)


class Wire(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    net: str = ""
    uuid: str = Field(default_factory=_uid)


class NetLabel(BaseModel):
    text: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    net: str = ""
    uuid: str = Field(default_factory=_uid)


class Junction(BaseModel):
    x: float = 0.0
    y: float = 0.0
    net: str = ""
    uuid: str = Field(default_factory=_uid)


class Schematic(BaseModel):
    name: str
    paper: str = "A4"
    uuid: str = Field(default_factory=_uid)
    symbols: list[SchSymbol] = []
    wires: list[Wire] = []
    labels: list[NetLabel] = []
    junctions: list[Junction] = []
    library_symbols: dict[str, SchLibrarySymbol] = Field(default_factory=dict)

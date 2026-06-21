"""Schematic models (KiCAD-independent).

Two layers live here:

* The hierarchical netlist model (``Sheet``/``SchPin``/``SheetInstance``), used by
  ``flatten_netlist`` to collapse a multi-sheet design into one global netlist.
* The drawable schematic model (``Schematic``/``SchSymbol``/``Wire``/``NetLabel``),
  a flat MVP that the ``.kicad_sch`` serializer turns into a file Eeschema opens.
  Live schematic editing over IPC does not exist yet (KiCAD's IPC API is PCB-only),
  so the file path is the reliable way to materialize a schematic.
"""

from __future__ import annotations

import uuid as _uuid

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(_uuid.uuid4())


# --- hierarchical netlist model -------------------------------------------


class SchPin(BaseModel):
    """A symbol pin on a sheet, connected to a local net by name."""

    symbol: str
    pin: str
    net: str


class SheetInstance(BaseModel):
    """A child sheet placed inside a parent, wiring child ports to parent nets."""

    sheet: "Sheet"
    # child hierarchical-label name -> parent local net name
    port_map: dict[str, str] = {}


class Sheet(BaseModel):
    """One schematic sheet."""

    name: str
    pins: list[SchPin] = []
    ports: list[str] = []                 # hierarchical labels exposed to the parent
    subsheets: list[SheetInstance] = []


SheetInstance.model_rebuild()
Sheet.model_rebuild()


# --- drawable schematic model (MVP) ---------------------------------------


class SchSymbol(BaseModel):
    """A placed symbol instance referencing a library symbol by ``lib_id``."""

    lib_id: str                           # e.g. "Device:R"
    reference: str                        # e.g. "R1"
    value: str = ""
    x: float = 0.0                        # mm
    y: float = 0.0                        # mm
    rotation: float = 0.0                 # degrees
    uuid: str = Field(default_factory=_uid)


class Wire(BaseModel):
    """A straight wire segment between two points (mm)."""

    x1: float
    y1: float
    x2: float
    y2: float
    uuid: str = Field(default_factory=_uid)


class NetLabel(BaseModel):
    """A local net label placed at a point (mm)."""

    text: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    uuid: str = Field(default_factory=_uid)


class Schematic(BaseModel):
    """A flat schematic document (MVP): symbols, wires and net labels."""

    name: str
    paper: str = "A4"
    uuid: str = Field(default_factory=_uid)
    symbols: list[SchSymbol] = []
    wires: list[Wire] = []
    labels: list[NetLabel] = []

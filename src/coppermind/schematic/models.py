"""Hierarchical schematic model (KiCAD-independent).

A schematic is a tree of sheets. Each sheet has symbol pins (each tagged with a
local net name) and may instantiate child sheets, mapping the child's
hierarchical labels (ports) to local nets in the parent. This is the minimal
shape needed to flatten a multi-sheet design into a single global netlist.
"""

from __future__ import annotations

from pydantic import BaseModel


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

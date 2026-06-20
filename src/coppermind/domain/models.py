"""Core PCB domain model.

This module is intentionally free of any KiCAD dependency. It is a plain,
serializable representation of a board that the orchestration, verification and
intelligence layers operate on. Backends (IPC / batch / memory) translate
between this model and KiCAD.

All coordinates are in millimetres. Angles are in degrees, counter-clockwise.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Layer(str, Enum):
    """The (small) subset of KiCAD layers Phase 0 needs."""

    F_CU = "F.Cu"
    B_CU = "B.Cu"
    F_SILKS = "F.SilkS"
    B_SILKS = "B.SilkS"
    EDGE_CUTS = "Edge.Cuts"


COPPER_LAYERS = {Layer.F_CU, Layer.B_CU}


class Point(BaseModel):
    """A 2D point in millimetres."""

    model_config = {"frozen": True}

    x: float
    y: float

    def distance_to(self, other: "Point") -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5


class Component(BaseModel):
    """A placed component (footprint instance)."""

    reference: str = Field(..., description="Designator, e.g. 'R1', 'U3'.")
    value: str = Field(default="", description="Value, e.g. '10k', 'STM32F103'.")
    footprint: str = Field(..., description="Library footprint id, e.g. 'R_0805_2012Metric'.")
    position: Point
    rotation: float = 0.0
    layer: Layer = Layer.F_CU
    # Simplified body extent (half-width, half-height in mm) used for collision checks.
    half_size: Point = Point(x=1.0, y=0.5)

    @field_validator("reference")
    @classmethod
    def _ref_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("component reference must not be blank")
        return v


class Net(BaseModel):
    """An electrical net."""

    name: str

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("net name must not be blank")
        return v


class Track(BaseModel):
    """A copper trace segment on a single layer."""

    net: str
    start: Point
    end: Point
    width: float = 0.25
    layer: Layer = Layer.F_CU

    @field_validator("width")
    @classmethod
    def _width_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("track width must be positive")
        return v


class Via(BaseModel):
    """A plated through/blind via connecting copper layers."""

    position: Point
    net: str = ""
    diameter: float = 0.8
    drill: float = 0.4
    from_layer: Layer = Layer.F_CU
    to_layer: Layer = Layer.B_CU


class BoardOutline(BaseModel):
    """Rectangular board outline (Phase 0 supports rectangles)."""

    width: float
    height: float
    origin: Point = Point(x=0.0, y=0.0)

    def contains(self, p: Point, margin: float = 0.0) -> bool:
        return (
            self.origin.x + margin <= p.x <= self.origin.x + self.width - margin
            and self.origin.y + margin <= p.y <= self.origin.y + self.height - margin
        )


class Board(BaseModel):
    """The full board state — the single document the system mutates.

    Components and nets are keyed by their natural identifiers so lookups,
    diffing and dedup checks are cheap and unambiguous.
    """

    name: str
    outline: BoardOutline | None = None
    components: dict[str, Component] = Field(default_factory=dict)
    nets: dict[str, Net] = Field(default_factory=dict)
    tracks: list[Track] = Field(default_factory=list)
    vias: list[Via] = Field(default_factory=list)

    def copy_deep(self) -> "Board":
        """Return an independent deep copy (used to snapshot transactions)."""
        return self.model_copy(deep=True)

"""Semantic circuit intermediate representation (Circuit IR).

The Circuit IR describes electrical intent, not drawing geometry. It is the
stable boundary between an LLM/planner and the KiCad schematic composer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ElectricalType(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    TRI_STATE = "tri_state"
    PASSIVE = "passive"
    FREE = "free"
    UNSPECIFIED = "unspecified"
    POWER_INPUT = "power_in"
    POWER_OUTPUT = "power_out"
    OPEN_COLLECTOR = "open_collector"
    OPEN_EMITTER = "open_emitter"
    NO_CONNECT = "no_connect"

    @classmethod
    def from_kicad(cls, value: str) -> "ElectricalType":
        aliases = {
            "power_input": cls.POWER_INPUT,
            "power_in": cls.POWER_INPUT,
            "power_output": cls.POWER_OUTPUT,
            "power_out": cls.POWER_OUTPUT,
            "open_collector": cls.OPEN_COLLECTOR,
            "open_emitter": cls.OPEN_EMITTER,
            "bidirectional": cls.BIDIRECTIONAL,
            "tri_state": cls.TRI_STATE,
            "no_connect": cls.NO_CONNECT,
        }
        try:
            return cls(value)
        except ValueError:
            return aliases.get(value, cls.UNSPECIFIED)


class Pin(BaseModel):
    """One real symbol pin as defined by KiCad's symbol library."""

    number: str
    name: str = ""
    electrical_type: ElectricalType = ElectricalType.UNSPECIFIED
    unit: int = 1
    shape: str = "line"


class Component(BaseModel):
    """Semantic component instance resolved from a real KiCad symbol."""

    reference: str
    symbol_id: str
    value: str = ""
    footprint: str = ""
    pins: dict[str, Pin] = Field(default_factory=dict)
    properties: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _pin_keys_match(self) -> "Component":
        for key, pin in self.pins.items():
            if key != pin.number:
                raise ValueError(f"pin key '{key}' does not match pin number '{pin.number}'")
        return self

    def pin(self, number_or_name: str) -> Pin:
        if number_or_name in self.pins:
            return self.pins[number_or_name]
        matches = [p for p in self.pins.values() if p.name == number_or_name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"pin name '{number_or_name}' is ambiguous on {self.reference}; use pin number"
            )
        raise KeyError(f"pin '{number_or_name}' not found on {self.reference}")


class PinRef(BaseModel):
    component: str
    pin: str

    def key(self) -> str:
        return f"{self.component}.{self.pin}"


class Net(BaseModel):
    """Electrical net connecting component pins by semantic identity."""

    name: str
    nodes: list[PinRef] = Field(default_factory=list)
    net_class: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class Constraint(BaseModel):
    """Planner/composer constraint without baking layout coordinates into intent."""

    kind: str
    targets: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    hard: bool = False


class Circuit(BaseModel):
    """A semantic circuit: components + nets + constraints."""

    name: str
    components: dict[str, Component] = Field(default_factory=dict)
    nets: dict[str, Net] = Field(default_factory=dict)
    constraints: list[Constraint] = Field(default_factory=list)

    def add_component(self, component: Component) -> None:
        if component.reference in self.components:
            raise ValueError(f"component '{component.reference}' already exists")
        self.components[component.reference] = component

    def connect(self, net_name: str, *nodes: PinRef) -> None:
        net = self.nets.setdefault(net_name, Net(name=net_name))
        existing = {node.key() for node in net.nodes}
        for node in nodes:
            self.resolve_pin(node)
            if node.key() not in existing:
                net.nodes.append(node)
                existing.add(node.key())

    def resolve_pin(self, ref: PinRef) -> Pin:
        component = self.components.get(ref.component)
        if component is None:
            raise KeyError(f"component '{ref.component}' does not exist")
        return component.pin(ref.pin)

    def validate_references(self) -> list[str]:
        errors: list[str] = []
        for net in self.nets.values():
            for node in net.nodes:
                try:
                    self.resolve_pin(node)
                except (KeyError, ValueError) as exc:
                    errors.append(f"{net.name}: {exc}")
        return errors

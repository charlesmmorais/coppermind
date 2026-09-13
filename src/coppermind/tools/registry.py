"""Tool registry + progressive discovery.

The default MCP surface is semantic. Coordinate-level PCB compatibility tools
remain discoverable on demand, while raw schematic geometry primitives are kept
internal so an LLM cannot regress to drawing wires by coordinates.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from coppermind.session import Session
from coppermind.tools.auto_placement import component_place_auto
from coppermind.tools.circuit import (
    component_freeze_placement,
    component_place_relative,
    connect_incremental,
    schematic_checkpoint,
    schematic_export_current,
)
from coppermind.tools.composer import COMPOSER_ROUTED_TOOLS
from coppermind.tools.core import component_place, net_create, net_route
from coppermind.tools.routed import ROUTED_TOOLS

ToolCallable = Callable[..., dict]

_CATEGORY_BY_PREFIX = {
    "project_": "project",
    "component_": "component",
    "net_": "net",
    "board_": "board",
    "design_": "design",
    "list_": "discovery",
    "get_": "discovery",
    "search_": "discovery",
    "execute_": "discovery",
    "connect_": "schematic",
    "schematic_": "schematic",
    "supplier_": "supplier",
    "route_": "routing",
    "variant_": "variant",
    "datasheet_": "datasheet",
}

_AGENT_HIDDEN = {"symbol_add", "wire_add"}
_LEGACY_ROUTED = (component_place, net_create, net_route)
_INCREMENTAL_ROUTED = (
    component_place_relative,
    component_place_auto,
    component_freeze_placement,
    connect_incremental,
    schematic_checkpoint,
    schematic_export_current,
)


def _category_for(name: str) -> str:
    for prefix, cat in _CATEGORY_BY_PREFIX.items():
        if name.startswith(prefix):
            return cat
    return "misc"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    summary: str
    func: ToolCallable
    parameters: list[str]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "summary": self.summary,
            "parameters": self.parameters,
        }


def _spec_from_func(func: ToolCallable) -> ToolSpec:
    params = [p for p in inspect.signature(func).parameters if p != "session"]
    summary = (func.__doc__ or "").strip().splitlines()[0] if func.__doc__ else ""
    return ToolSpec(
        name=func.__name__,
        category=_category_for(func.__name__),
        summary=summary,
        func=func,
        parameters=params,
    )


class ToolRegistry:
    """Holds routed tools and powers the discovery operations."""

    def __init__(self, funcs: tuple[ToolCallable, ...]) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for fn in funcs:
            spec = _spec_from_func(fn)
            self._specs[spec.name] = spec

    def list_categories(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for spec in self._specs.values():
            counts[spec.category] = counts.get(spec.category, 0) + 1
        return dict(sorted(counts.items()))

    def get_category_tools(self, category: str) -> list[dict]:
        return [
            {"name": s.name, "summary": s.summary}
            for s in self._specs.values()
            if s.category == category
        ]

    def search_tools(self, query: str) -> list[dict]:
        q = query.lower().strip()
        hits = [
            {"name": s.name, "category": s.category, "summary": s.summary}
            for s in self._specs.values()
            if q in s.name.lower() or q in s.summary.lower()
        ]
        return sorted(hits, key=lambda h: h["name"])

    def get_tool_schema(self, name: str) -> dict:
        if name not in self._specs:
            raise KeyError(f"unknown tool '{name}'")
        return self._specs[name].schema()

    def execute_tool(self, session: Session, name: str, arguments: dict | None = None) -> dict:
        if name not in self._specs:
            raise KeyError(f"unknown tool '{name}'")
        return self._specs[name].func(session, **(arguments or {}))

    @property
    def names(self) -> list[str]:
        return sorted(self._specs)


_ROUTED_AGENT_TOOLS = tuple(fn for fn in ROUTED_TOOLS if fn.__name__ not in _AGENT_HIDDEN)
_ALL_ROUTED_TOOLS = cast(
    tuple[ToolCallable, ...],
    _ROUTED_AGENT_TOOLS + COMPOSER_ROUTED_TOOLS + _LEGACY_ROUTED + _INCREMENTAL_ROUTED,
)
REGISTRY = ToolRegistry(_ALL_ROUTED_TOOLS)

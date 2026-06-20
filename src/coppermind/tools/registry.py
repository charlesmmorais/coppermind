"""Tool registry + progressive discovery.

This is the honest version of the reference project's inert "router": a small
core set stays always-visible, while the long tail of routed tools is found on
demand. The model browses categories, searches by keyword, fetches a single
tool's schema, and invokes it via ``execute_tool`` — so routed definitions never
sit in context until they're needed. A CI budget test keeps it that way.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass

from coppermind.session import Session
from coppermind.tools.routed import ROUTED_TOOLS

_CATEGORY_BY_PREFIX = {
    "project_": "project",
    "component_": "component",
    "net_": "net",
    "board_": "board",
    "design_": "design",
    "supplier_": "supplier",
    "route_": "routing",
    "variant_": "variant",
    "datasheet_": "datasheet",
}


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
    func: Callable[..., dict]
    parameters: list[str]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "summary": self.summary,
            "parameters": self.parameters,
        }


def _spec_from_func(func: Callable[..., dict]) -> ToolSpec:
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

    def __init__(self, funcs: tuple[Callable[..., dict], ...]) -> None:
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


REGISTRY = ToolRegistry(ROUTED_TOOLS)

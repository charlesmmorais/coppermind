"""Discovery tools — always visible, cheap, and the gateway to routed tools.

These five small tools let the model navigate the long tail without paying its
context cost up front. They wrap the shared REGISTRY.
"""

from __future__ import annotations

from coppermind.session import Session
from coppermind.tools.registry import REGISTRY


def list_tool_categories(session: Session) -> dict:
    """List routed tool categories and how many tools each holds."""
    return {"categories": REGISTRY.list_categories()}


def get_category_tools(session: Session, category: str) -> dict:
    """List the routed tools in a category (name + one-line summary)."""
    return {"category": category, "tools": REGISTRY.get_category_tools(category)}


def search_tools(session: Session, query: str) -> dict:
    """Find routed tools whose name or summary matches a keyword."""
    return {"query": query, "matches": REGISTRY.search_tools(query)}


def get_tool_schema(session: Session, name: str) -> dict:
    """Fetch the full schema (parameters) for a single routed tool."""
    return REGISTRY.get_tool_schema(name)


def execute_tool(session: Session, name: str, arguments: dict | None = None) -> dict:
    """Run a routed tool by name with the given arguments."""
    return REGISTRY.execute_tool(session, name, arguments)


DISCOVERY_TOOLS = (
    list_tool_categories,
    get_category_tools,
    search_tools,
    get_tool_schema,
    execute_tool,
)

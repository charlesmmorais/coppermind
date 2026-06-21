"""MCP server entrypoint (FastMCP).

Thin registration layer. It exposes a *lean* always-visible set — the core tools
plus five discovery tools — and keeps the routed long tail behind progressive
discovery (browse categories / search / fetch schema / execute_tool). All real
logic lives in the layers below, so this file stays small and testable.

Run with:  coppermind         (after `pip install -e .`)
       or:  python -m coppermind.server
"""

from __future__ import annotations

import functools
import inspect
import logging

from coppermind.session import Session
from coppermind.tools import CORE_TOOLS, DISCOVERY_TOOLS

logger = logging.getLogger("coppermind")


def _bind_tool(fn, session):  # type: ignore[no-untyped-def]
    """Bind ``session`` as the first argument and hide it from the public schema.

    FastMCP/pydantic build each tool's JSON schema from the function signature.
    A plain ``functools.partial`` still exposes the original ``session: Session``
    parameter, and pydantic cannot emit a schema for that type. We therefore wrap
    the call and publish a signature/annotations that omit ``session`` entirely.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(session, *args, **kwargs)

    sig = inspect.signature(fn)
    params = [p for name, p in sig.parameters.items() if name != "session"]
    wrapper.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]
    wrapper.__annotations__ = {
        k: v for k, v in getattr(fn, "__annotations__", {}).items() if k != "session"
    }
    if hasattr(wrapper, "__wrapped__"):
        del wrapper.__wrapped__
    return wrapper


def build_server():  # type: ignore[no-untyped-def]
    """Create and configure the FastMCP server."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("coppermind")
    session = Session()
    logger.info("Backend: %s", session.backend.name)

    for fn in CORE_TOOLS + DISCOVERY_TOOLS:
        bound = _bind_tool(fn, session)
        mcp.add_tool(bound, name=fn.__name__, description=(fn.__doc__ or "").strip())

    @mcp.resource("kicad://project/current/preview.svg")
    def board_preview() -> str:
        """Live SVG preview of the current board (committed state)."""
        if session.document is None:
            return "<svg xmlns='http://www.w3.org/2000/svg'/>"
        data = session.backend.render(session.document.board)
        return (data or b"").decode("utf-8")

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    build_server().run()


if __name__ == "__main__":
    main()

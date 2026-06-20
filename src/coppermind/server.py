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
import logging

from coppermind.session import Session
from coppermind.tools import CORE_TOOLS, DISCOVERY_TOOLS

logger = logging.getLogger("coppermind")


def build_server():  # type: ignore[no-untyped-def]
    """Create and configure the FastMCP server.

    Imported lazily so the rest of the package (domain/verification/transactions)
    works even when the MCP SDK isn't installed (e.g. in unit-test envs).
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("coppermind")
    session = Session()
    logger.info("Backend: %s", session.backend.name)

    for fn in CORE_TOOLS + DISCOVERY_TOOLS:
        bound = functools.wraps(fn)(functools.partial(fn, session))
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

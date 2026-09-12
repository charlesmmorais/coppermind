"""MCP server entrypoint (FastMCP).

The same Coppermind server can be exposed in two ways:

* ``stdio`` — local subprocess transport, ideal for Claude Desktop/Code and other
  local MCP hosts;
* ``streamable-http`` — loopback HTTP transport, ideal for a trusted MCP tunnel
  or gateway used by a remote-capable client such as ChatGPT.

The HTTP transport is deliberately loopback-only. Coppermind keeps one
in-process design session, so directly exposing the process to a network would
mix project state between clients and would provide no application-level auth.
Put authentication/tunnelling in front of the localhost endpoint instead of
binding Coppermind itself to a public interface.
"""

from __future__ import annotations

import argparse
import functools
import inspect
import ipaddress
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from coppermind.session import Session
from coppermind.tools import CORE_TOOLS, DISCOVERY_TOOLS

logger = logging.getLogger("coppermind")

Transport = Literal["stdio", "streamable-http"]


@dataclass(frozen=True)
class ServerOptions:
    """Runtime transport configuration for the MCP server."""

    transport: Transport = "stdio"
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/mcp"
    log_level: str = "INFO"

    @property
    def endpoint(self) -> str | None:
        if self.transport != "streamable-http":
            return None
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"http://{host}:{self.port}{self.path}"


def _env_port(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


def _normalize_path(value: str) -> str:
    path = value.strip() or "/mcp"
    if not path.startswith("/"):
        path = f"/{path}"
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _is_loopback_host(host: str) -> bool:
    value = host.strip().lower()
    if value == "localhost":
        return True
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def parse_server_options(argv: Sequence[str] | None = None) -> ServerOptions:
    """Parse CLI/environment configuration without starting the server."""

    parser = argparse.ArgumentParser(
        prog="coppermind",
        description="Coppermind MCP server for KiCad",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("COPPERMIND_TRANSPORT", "stdio"),
        help="MCP transport (default: stdio; env COPPERMIND_TRANSPORT)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("COPPERMIND_HTTP_HOST", "127.0.0.1"),
        help="Streamable HTTP loopback bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_port("COPPERMIND_HTTP_PORT", 8765),
        help="Streamable HTTP port (default: 8765)",
    )
    parser.add_argument(
        "--path",
        default=os.getenv("COPPERMIND_HTTP_PATH", "/mcp"),
        help="Streamable HTTP MCP path (default: /mcp)",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=os.getenv("LOG_LEVEL", "INFO").upper(),
        help="logging level (default: INFO; env LOG_LEVEL)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    return ServerOptions(
        transport=args.transport,
        host=args.host.strip(),
        port=args.port,
        path=_normalize_path(args.path),
        log_level=args.log_level,
    )


def _bind_tool(fn: Any, session: Session) -> Any:
    """Bind ``session`` as the first argument and hide it from the public schema.

    FastMCP/pydantic build each tool's JSON schema from the function signature.
    A plain ``functools.partial`` still exposes the original ``session: Session``
    parameter, and pydantic cannot emit a schema for that type. We therefore wrap
    the call and publish a signature/annotations that omit ``session`` entirely.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
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


def build_server(options: ServerOptions | None = None) -> Any:
    """Create a FastMCP v1 server with transport settings fixed at construction."""
    from mcp.server.fastmcp import FastMCP

    runtime = options or ServerOptions()
    mcp = FastMCP(
        "coppermind",
        host=runtime.host,
        port=runtime.port,
        streamable_http_path=runtime.path,
    )
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


def run_server(options: ServerOptions, server: Any | None = None) -> None:
    """Run a configured MCP server, enforcing safe HTTP defaults."""

    if options.transport == "streamable-http" and not _is_loopback_host(options.host):
        raise ValueError(
            "Coppermind Streamable HTTP is loopback-only. Bind to 127.0.0.1, "
            "localhost or ::1 and place a trusted authenticated MCP tunnel/proxy "
            "in front of it when a remote client must connect."
        )

    mcp = server or build_server(options)
    if options.transport == "stdio":
        logger.info("MCP transport: stdio")
        mcp.run(transport="stdio")
        return

    logger.info("MCP transport: Streamable HTTP at %s", options.endpoint)
    logger.warning(
        "Streamable HTTP shares one Coppermind design session per process; "
        "treat this endpoint as a single-user service."
    )
    # FastMCP v1 takes host/port/path at construction time.  Keeping those
    # settings out of run() is what makes this compatible with mcp>=1.30,<2.
    mcp.run(transport="streamable-http")


def main(argv: Sequence[str] | None = None) -> None:
    options = parse_server_options(argv)
    logging.basicConfig(level=getattr(logging, options.log_level))
    try:
        run_server(options)
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

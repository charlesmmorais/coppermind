from __future__ import annotations

from typing import Any

import pytest

from coppermind.server import ServerOptions, build_server, parse_server_options, run_server


class FakeServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, transport: str = "stdio", **kwargs: Any) -> None:
        self.calls.append((transport, kwargs))


def test_server_options_default_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "COPPERMIND_TRANSPORT",
        "COPPERMIND_HTTP_HOST",
        "COPPERMIND_HTTP_PORT",
        "COPPERMIND_HTTP_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)

    options = parse_server_options([])

    assert options == ServerOptions()
    assert options.endpoint is None


def test_server_options_support_http_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPPERMIND_TRANSPORT", "streamable-http")
    monkeypatch.setenv("COPPERMIND_HTTP_HOST", "localhost")
    monkeypatch.setenv("COPPERMIND_HTTP_PORT", "9001")
    monkeypatch.setenv("COPPERMIND_HTTP_PATH", "custom/mcp/")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    options = parse_server_options([])

    assert options.transport == "streamable-http"
    assert options.host == "localhost"
    assert options.port == 9001
    assert options.path == "/custom/mcp"
    assert options.log_level == "DEBUG"
    assert options.endpoint == "http://localhost:9001/custom/mcp"


def test_build_server_configures_fastmcp_v1_http_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COPPERMIND_BACKEND", "memory")
    options = ServerOptions(
        transport="streamable-http",
        host="127.0.0.1",
        port=9002,
        path="/custom-mcp",
    )

    server = build_server(options)

    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 9002
    assert server.settings.streamable_http_path == "/custom-mcp"


def test_stdio_dispatches_without_http_options() -> None:
    server = FakeServer()

    run_server(ServerOptions(), server)

    assert server.calls == [("stdio", {})]


def test_streamable_http_dispatches_v1_transport_only() -> None:
    server = FakeServer()
    options = ServerOptions(
        transport="streamable-http",
        host="127.0.0.1",
        port=8765,
        path="/mcp",
    )

    run_server(options, server)

    assert server.calls == [("streamable-http", {})]


def test_streamable_http_accepts_ipv6_loopback() -> None:
    server = FakeServer()
    options = ServerOptions(transport="streamable-http", host="::1")

    run_server(options, server)

    assert options.endpoint == "http://[::1]:8765/mcp"
    assert server.calls == [("streamable-http", {})]


def test_streamable_http_rejects_non_loopback_before_server_build() -> None:
    server = FakeServer()
    options = ServerOptions(transport="streamable-http", host="0.0.0.0")

    with pytest.raises(ValueError, match="loopback-only"):
        run_server(options, server)

    assert server.calls == []


def test_invalid_http_port_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPPERMIND_HTTP_PORT", "70000")

    with pytest.raises(ValueError, match="between 1 and 65535"):
        parse_server_options([])

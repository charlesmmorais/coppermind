from __future__ import annotations

from typing import Any

import pytest

from coppermind.server import ServerOptions, parse_server_options, run_server


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
        "COPPERMIND_ALLOW_REMOTE_HTTP",
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
    monkeypatch.setenv("COPPERMIND_ALLOW_REMOTE_HTTP", "true")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    options = parse_server_options([])

    assert options.transport == "streamable-http"
    assert options.host == "localhost"
    assert options.port == 9001
    assert options.path == "/custom/mcp"
    assert options.allow_remote_http is True
    assert options.log_level == "DEBUG"
    assert options.endpoint == "http://localhost:9001/custom/mcp"


def test_stdio_dispatches_without_http_options() -> None:
    server = FakeServer()

    run_server(ServerOptions(), server)

    assert server.calls == [("stdio", {})]


def test_streamable_http_dispatches_expected_bind_options() -> None:
    server = FakeServer()
    options = ServerOptions(
        transport="streamable-http",
        host="127.0.0.1",
        port=8765,
        path="/mcp",
    )

    run_server(options, server)

    assert server.calls == [
        (
            "streamable-http",
            {
                "host": "127.0.0.1",
                "port": 8765,
                "streamable_http_path": "/mcp",
            },
        )
    ]


def test_streamable_http_rejects_non_loopback_by_default() -> None:
    server = FakeServer()
    options = ServerOptions(transport="streamable-http", host="0.0.0.0")

    with pytest.raises(ValueError, match="Refusing to expose"):
        run_server(options, server)

    assert server.calls == []


def test_streamable_http_allows_explicit_remote_bind() -> None:
    server = FakeServer()
    options = ServerOptions(
        transport="streamable-http",
        host="0.0.0.0",
        port=8765,
        path="/mcp",
        allow_remote_http=True,
    )

    run_server(options, server)

    assert server.calls[0][0] == "streamable-http"
    assert server.calls[0][1]["host"] == "0.0.0.0"


def test_invalid_http_port_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPPERMIND_HTTP_PORT", "70000")

    with pytest.raises(ValueError, match="between 1 and 65535"):
        parse_server_options([])

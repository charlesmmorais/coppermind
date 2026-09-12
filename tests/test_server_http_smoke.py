from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


_REQUIRED_TOOLS = {
    "project_create",
    "find_symbol",
    "component_add",
    "create_net",
    "connect_pins",
    "inspect_component",
    "design_preview",
    "design_commit",
    "design_rollback",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(process: subprocess.Popen[str], port: int, timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"Streamable HTTP server exited early:\n{stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("Timed out waiting for the Streamable HTTP server")


async def _list_tools(url: str) -> set[str]:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            return {tool.name for tool in response.tools}


def test_streamable_http_real_mcp_handshake() -> None:
    port = _free_port()
    env = os.environ.copy()
    env["COPPERMIND_BACKEND"] = "memory"
    env["PYTHONUNBUFFERED"] = "1"
    repo_root = Path(__file__).resolve().parents[1]

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "coppermind.server",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--path",
            "/mcp",
        ],
        cwd=repo_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(process, port)
        tools = asyncio.run(_list_tools(f"http://127.0.0.1:{port}/mcp"))
        assert _REQUIRED_TOOLS <= tools
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

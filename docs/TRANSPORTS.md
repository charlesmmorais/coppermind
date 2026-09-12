# MCP Transports — stdio and Streamable HTTP

Coppermind exposes the same tools/resources through two MCP transports. The choice of
transport does not change Circuit IR, the composer, ERC, or safety gates; it only
changes **how the client talks to the server**.

## 1. stdio

Use this when the MCP client runs on the same machine and can launch Coppermind as a
subprocess.

```bash
coppermind --transport stdio
```

`stdio` is the default, so this is equivalent:

```bash
coppermind
```

This is the recommended path for Claude Desktop/Code and other local MCP hosts.

Example:

```json
{
  "mcpServers": {
    "coppermind": {
      "command": "coppermind",
      "args": ["--transport", "stdio"],
      "env": {
        "COPPERMIND_BACKEND": "auto"
      }
    }
  }
}
```

## 2. Streamable HTTP

Use this when a client must reach Coppermind over HTTP, typically through a trusted
MCP tunnel or gateway.

```bash
coppermind \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --path /mcp
```

Endpoint:

```text
http://127.0.0.1:8765/mcp
```

Equivalent environment configuration:

```bash
export COPPERMIND_TRANSPORT=streamable-http
export COPPERMIND_HTTP_HOST=127.0.0.1
export COPPERMIND_HTTP_PORT=8765
export COPPERMIND_HTTP_PATH=/mcp
coppermind
```

## 3. HTTP endpoint security

Coppermind **refuses non-loopback binds**. Accepted hosts are:

- `127.0.0.1`;
- `localhost`;
- `::1`.

This is deliberate. The current server:

- keeps **one design session per process**;
- does not implement multi-user authentication;
- exposes write tools that can modify a KiCad design;
- should be treated as a privileged local automation process.

Do not expose `0.0.0.0:8765` directly to a LAN or the public Internet.

The MCP SDK also applies DNS-rebinding protection to Streamable HTTP. A generic public
reverse proxy may require explicit Host/Origin security configuration at the gateway.
Coppermind intentionally does not disable that protection.

## 4. ChatGPT / cloud MCP clients

A cloud client cannot directly reach your computer's `127.0.0.1`. The recommended
shape is:

```text
cloud MCP client
        │
        │ HTTPS / MCP Streamable HTTP
        ▼
authenticated MCP tunnel/gateway
        │
        │ local connection
        ▼
http://127.0.0.1:8765/mcp
        │
        ▼
Coppermind
        │
        ▼
KiCad / kicad-cli
```

To create schematics, the client/workspace must support **custom MCP servers and
write-capable tools**. Streamable HTTP does not grant those permissions by itself.

When the client product offers a secure local MCP tunnel, prefer that over publishing
Coppermind directly.

## 5. Backend and transport are independent

All of these are valid combinations:

```text
stdio + MemoryBackend
stdio + IPCBackend
Streamable HTTP + MemoryBackend
Streamable HTTP + IPCBackend
```

For a live KiCad session:

```bash
COPPERMIND_BACKEND=ipc coppermind --transport stdio
```

or:

```bash
COPPERMIND_BACKEND=ipc coppermind --transport streamable-http
```

`COPPERMIND_BACKEND=auto` attempts IPC and gracefully falls back to memory when KiCad
is not reachable.

## 6. CLI options

```text
--transport {stdio,streamable-http}
--host HOST
--port PORT
--path PATH
--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
```

HTTP defaults:

```text
host = 127.0.0.1
port = 8765
path = /mcp
```

Environment variables:

```text
COPPERMIND_TRANSPORT
COPPERMIND_HTTP_HOST
COPPERMIND_HTTP_PORT
COPPERMIND_HTTP_PATH
LOG_LEVEL
```

## 7. Troubleshooting

### Server starts but client cannot connect

Verify the exact endpoint includes `/mcp`:

```text
http://127.0.0.1:8765/mcp
```

Then verify that the tunnel/gateway really forwards to that local address.

### Error when using `0.0.0.0`

Expected behavior. Coppermind blocks direct network exposure. Use loopback plus an
authenticated tunnel/gateway.

### MCP connects but KiCad is not modified

Transport and backend are separate layers. Check:

1. `COPPERMIND_BACKEND=ipc` or `auto`;
2. KiCad is running;
3. **Preferences → Plugins → Enable IPC API Server** is enabled;
4. `kicad-python` is installed via `pip install -e ".[ipc]"`.

### Schematic is generated but does not appear as live editor mutations

On KiCad 10, the primary schematic path still uses `.kicad_sch` materialization plus
`kicad-cli`. Live IPC is more complete on the PCB side; KiCad 11 schematic IPC will be
adopted progressively as that API stabilizes.

## 8. Session model

Today `build_server()` creates one `Session` and binds it to the tool surface. This is
appropriate for one user controlling one design context per process, whether over
stdio or through a dedicated HTTP tunnel.

A future multi-user service would need:

```text
identity/authentication
      ↓
MCP session
      ↓
isolated Coppermind Session
      ↓
isolated workspace/project
```

Until then, **one process = one user/design context**.

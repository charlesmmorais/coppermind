<div align="center">

# 🔶 Coppermind

### Electronic-engineering copilot for KiCad — semantic, transactional, verified MCP

[![CI](https://github.com/charlesmmorais/coppermind/actions/workflows/ci.yml/badge.svg)](https://github.com/charlesmmorais/coppermind/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![KiCad 10/11](https://img.shields.io/badge/KiCad-10%20%7C%2011-green.svg)](https://www.kicad.org/)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange.svg)](https://modelcontextprotocol.io/)

[🇧🇷 Português](README.md) · **🇺🇸 English**

</div>

---

> **Describe the circuit, not the coordinates.** Coppermind resolves real KiCad
> symbols, builds a Circuit IR, composes the schematic, runs ERC, reviews visual
> organization, and only accepts changes after safety gates pass.

**Coppermind** is a Python MCP server for electronic-design workflows in **KiCad**.
The primary schematic path is semantic: the agent works with
`Component / Pin / Net / Constraint`, while Coppermind lowers that intent into a
real `.kicad_sch` using symbols from the user's installed KiCad libraries.

The server supports **two MCP transports**:

- **stdio** — a local MCP host launches Coppermind as a subprocess;
- **Streamable HTTP** — a local `/mcp` endpoint suitable for a trusted MCP
  tunnel/gateway when the client is outside the machine.

HTTP is intentionally **loopback-only**. Coppermind is not meant to be exposed
directly to the public Internet: it currently keeps one design session per process
and does not implement application-level multi-user authentication.

![Coppermind architecture](docs/architecture.svg)

---

## Current status

The schematic workflow now implements five semantic phases:

| Phase | Delivered capability |
| --- | --- |
| **1 — Circuit IR + real symbols** | `Component`, `Pin`, `Net`, `Constraint`; `.kicad_sym`/`.kicad_symdir` resolution; no generic two-pin fallback. |
| **2 — Semantic tools** | `find_symbol`, `component_add`, `create_net`, `connect_pins`, `inspect_component`; the LLM does not draw wires by coordinates. |
| **3 — Semantic Composer** | Circuit IR → placement → net graph → wires/labels/junctions → `.kicad_sch` → real KiCad ERC. |
| **4 — Visual Reviewer** | visual score, real KiCad SVG/PDF, deterministic reflow and optional multimodal review. |
| **5 — Visual Auto-Fix** | typed Layout Action IR, copy-on-write candidates, safety gates, ERC diff and rollback. |

```text
ChatGPT / Claude / another MCP client
              │
       stdio or Streamable HTTP
              │
              ▼
          Coppermind
              │
              ▼
          Circuit IR
              │
              ▼
      Semantic Composer
              │
              ▼
      real .kicad_sch
              │
      ┌───────┴────────┐
      ▼                ▼
   KiCad ERC       SVG / PDF
      │                │
      └───────┬────────┘
              ▼
       Visual Reviewer
              │
       Layout Action IR
              │
        accept / rollback
```

---

## Installation

### Requirements

- Python **3.11+**;
- KiCad **10+** for real use;
- `kicad-cli` on `PATH` for headless ERC/rendering;
- for live IPC: the `kicad-python` package and KiCad's IPC API enabled.

Coppermind intentionally stays on the **MCP Python SDK 1.x** API while it uses
`FastMCP`: `mcp>=1.30,<2`. This avoids an accidental upgrade across the SDK v2
breaking API boundary.

### Linux/macOS

```bash
git clone https://github.com/charlesmmorais/coppermind.git
cd coppermind
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[ipc]"
```

### Windows / PowerShell

```powershell
git clone https://github.com/charlesmmorais/coppermind.git
cd coppermind
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[ipc]"
```

For development:

```bash
pip install -e ".[dev,ipc]"
pytest
```

For live IPC, enable this in KiCad:

**Preferences → Plugins → Enable IPC API Server**

---

## Running the MCP server

### Option A — stdio

This is the default and the best fit for local MCP hosts:

```bash
coppermind
```

or explicitly:

```bash
coppermind --transport stdio
```

### Option B — Streamable HTTP

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

Equivalent environment variables:

```bash
COPPERMIND_TRANSPORT=streamable-http
COPPERMIND_HTTP_HOST=127.0.0.1
COPPERMIND_HTTP_PORT=8765
COPPERMIND_HTTP_PATH=/mcp
COPPERMIND_BACKEND=auto
coppermind
```

> **Security:** the process refuses `0.0.0.0`, LAN IPs, and non-loopback hostnames.
> For ChatGPT or another remote client, keep Coppermind on `127.0.0.1` and put an
> **authenticated trusted MCP tunnel/gateway** in front of it. See
> [`docs/TRANSPORTS.md`](docs/TRANSPORTS.md).

---

## Connecting MCP clients

### Claude Desktop / local clients

Example `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "coppermind": {
      "command": "coppermind",
      "args": ["--transport", "stdio"],
      "env": {
        "COPPERMIND_BACKEND": "auto",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

If `coppermind` is not on `PATH`, use the virtual environment's absolute executable
path.

### ChatGPT / remote MCP client

Coppermind now exposes Streamable HTTP, but `127.0.0.1` only exists on your local
machine. A cloud client needs a trusted bridge:

```text
ChatGPT
   │
   │ MCP Streamable HTTP
   ▼
authenticated MCP tunnel/gateway
   │
   ▼
127.0.0.1:8765/mcp
   │
   ▼
Coppermind → KiCad
```

The client/workspace must support **custom MCP servers and write-capable tools** to
create or modify a schematic. HTTP transport by itself does not grant those
permissions.

---

## KiCad backend selection

```bash
COPPERMIND_BACKEND=auto    # IPC when reachable, otherwise MemoryBackend
COPPERMIND_BACKEND=ipc     # require an accessible KiCad IPC session
COPPERMIND_BACKEND=memory  # development/offline
```

| Backend | Primary use |
| --- | --- |
| `MemoryBackend` | domain tests and offline work |
| `IPCBackend` | live KiCad access through `kicad-python` / kipy |
| `BatchBackend` | headless DRC/render/export through `kicad-cli` |

On KiCad 10 the schematic path is intentionally hybrid: Circuit IR + composer write
the `.kicad_sch`; `kicad-cli` performs real ERC and rendering. As the KiCad 11
schematic IPC API matures, that backend can replace parts of the materialization
layer without changing the semantic agent tools.

---

## Recommended agent workflow

The **9 core tools** are intent-oriented:

```text
project_create
find_symbol
component_add
create_net
connect_pins
inspect_component
design_preview
design_commit
design_rollback
```

Another **5 progressive-discovery tools** expose the long tail without filling the
model's context:

```text
list_tool_categories
get_category_tools
search_tools
get_tool_schema
execute_tool
```

Example semantic authoring flow:

```text
find_symbol("resistor")
component_add(reference="R1", symbol="Device:R", value="10k")
component_add(reference="C1", symbol="Device:C", value="100nF")
create_net(name="SENSE")
connect_pins(net="SENSE", pins=["R1.2", "C1.1"])
design_preview()
design_commit()
```

Raw schematic geometry primitives such as `symbol_add` and `wire_add` remain
internal and are not exposed to the agent. Coordinate-level PCB operations remain
available only as routed compatibility tools.

---

## Composer, ERC and visual review

`design_preview` and `design_commit` automatically execute the safe schematic
pipeline:

```text
Circuit IR
 → compose
 → visual review/reflow
 → .kicad_sch serialization
 → KiCad ERC
 → gate
```

Additional tools are discovered on demand:

```text
schematic_compose
schematic_erc
schematic_export_composed
schematic_visual_review
schematic_visual_optimize
schematic_visual_plan
schematic_visual_apply
schematic_visual_autofix
```

Visual auto-fix **cannot change electrical intent**. It only executes bounded typed
geometry actions (`move_near`, `align`, `compact_block`, etc.) on a copy of the
schematic. A candidate is discarded if the score regresses, a new ERC violation
appears, or Circuit IR changes.

Detailed documentation:

- [`docs/MULTIMODAL_VISUAL_REVIEW.md`](docs/MULTIMODAL_VISUAL_REVIEW.md)
- [`docs/VISUAL_AUTOFIX.md`](docs/VISUAL_AUTOFIX.md)

---

## Optional multimodal reviewer

The deterministic reviewer works without any external service. To add a multimodal
critic, configure a compatible provider:

```bash
COPPERMIND_VISUAL_PROVIDER=openai
OPENAI_API_KEY=...
COPPERMIND_VISUAL_MODEL=<multimodal-model>
```

When enabled, the real KiCad PDF and a bounded Circuit IR context are sent to that
provider. Do not enable this for sensitive designs unless the resulting data transfer
is acceptable under your security and privacy policy.

---

## PCB, autorouting and integrations

The historical PCB core remains available: transactions, DRC, undo/redo, variants,
supplier search, datasheets, `.kicad_pcb` export and Freerouting.

Autorouting guide:

[`docs/AUTORROTEAMENTO.md`](docs/AUTORROTEAMENTO.md)

```text
KiCad → Specctra DSN → Freerouting → SES → Coppermind
                                      ↓
                                preview / DRC
                                      ↓
                                commit / rollback
```

---

## Architectural safety guarantees

Coppermind is designed so the model does not become an unrestricted code executor:

- no arbitrary Python generated by the model is executed;
- symbols are resolved from real KiCad libraries;
- unresolved symbols fail explicitly;
- Circuit IR remains the electrical source of truth;
- changes go through preview/commit/rollback;
- ERC/DRC are part of the gate;
- visual auto-fix is copy-on-write and geometry-only;
- tool file paths are validated;
- Streamable HTTP is loopback-only;
- the multimodal provider is optional and has a documented data boundary.

---

## Tests and CI

The CI workflow runs:

- Python 3.11 and 3.12;
- Ruff;
- pytest + coverage;
- mypy;
- a **blocking** real KiCad 10 integration job;
- schematic serialization, ERC, SVG/PDF rendering and Visual Auto-Fix against KiCad.

Critical architectural claims are intended to be executable CI invariants, not just
README statements.

---

## Current limitations

- Streamable HTTP is **single-user per process**, not multi-tenant.
- The HTTP endpoint has no built-in application authentication; use a trusted tunnel
  or gateway.
- KiCad 10 schematic creation uses `.kicad_sch` files + `kicad-cli`; live schematic
  IPC will be adopted as the relevant API stabilizes.
- The multimodal Visual Reviewer is probabilistic and optional; deterministic gates
  remain the safety authority.
- The PCB path still contains more geometry-level legacy operations than the semantic
  schematic path.
- Engineering review remains necessary before manufacturing hardware.

---

## Documentation

See [`docs/README.md`](docs/README.md) for the documentation index:

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — current architecture and decisions;
- [`docs/TRANSPORTES.md`](docs/TRANSPORTES.md) — Portuguese transport guide;
- [`docs/TRANSPORTS.md`](docs/TRANSPORTS.md) — stdio, Streamable HTTP and tunnelling;
- [`docs/MULTIMODAL_VISUAL_REVIEW.md`](docs/MULTIMODAL_VISUAL_REVIEW.md);
- [`docs/VISUAL_AUTOFIX.md`](docs/VISUAL_AUTOFIX.md);
- [`docs/AUTORROTEAMENTO.md`](docs/AUTORROTEAMENTO.md).

---

## Contributing

Before opening a PR:

```bash
pip install -e ".[dev,ipc]"
ruff check src tests
pytest
mypy src
```

Keep the core invariants intact: electrical intent belongs in Circuit IR, geometry is
derived, discovery is progressive, changes are reversible, and model-generated
arbitrary code is never executed.

## License

MIT. See [`LICENSE`](LICENSE).

Coppermind is an engineering-assistance tool. ERC/DRC, rules and AI reduce risk but
do not replace electrical, thermal, mechanical, regulatory and safety validation
before manufacturing.

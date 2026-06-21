<div align="center">

# 🔶 Coppermind

### An AI PCB-design copilot for KiCAD — an **IPC-first, transactional, verified** MCP server

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![KiCAD 10/11](https://img.shields.io/badge/KiCAD-10%20%7C%2011-green.svg)](https://www.kicad.org/)
[![Tests](https://img.shields.io/badge/tests-183%20passing-brightgreen.svg)](#-quality-tests--ci)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange.svg)](https://modelcontextprotocol.io/)

[🇧🇷 Português (main)](README.md) · **🇺🇸 English**

</div>

---

> **Describe what you want to build.** Coppermind proposes, **verifies**,
> **explains**, and only then applies — and **everything is reversible**.

Coppermind is an [MCP](https://modelcontextprotocol.io/) server that lets AI
assistants (like Claude) design PCBs in KiCAD through **natural language**. Unlike
a thin command translator, it **previews and verifies every change before
writing** (including native KiCAD DRC/ERC), keeps everything **reversible**, and
grounds its suggestions in a **citable electrical-engineering knowledge base**.

<div align="center">

![Coppermind architecture](docs/architecture.svg)

</div>

---

## 📑 Table of contents

- [Why Coppermind exists](#-why-coppermind-exists)
- [What makes it different](#-what-makes-it-different)
- [Architecture](#-architecture)
- [The transactional model](#-the-transactional-model)
- [Installation](#-installation)
- [MCP client setup](#-mcp-client-setup)
- [Backends](#-backends)
- [Tool catalog](#-tool-catalog)
- [Design intelligence](#-design-intelligence)
- [Autorouting (Freerouting)](#-autorouting-freerouting)
- [Suppliers (JLCPCB/LCSC) and datasheets](#-suppliers-jlcpcblcsc-and-datasheets)
- [Usage examples](#-usage-examples)
- [Quality: tests & CI](#-quality-tests--ci)
- [Project layout](#-project-layout)
- [Roadmap / phase status](#-roadmap--phase-status)
- [Honest limitations](#-honest-limitations)
- [Contributing](#-contributing)
- [License, credits & disclaimer](#-license-credits--disclaimer)

---

## 🎯 Why Coppermind exists

The project grew out of a **critical study** of existing KiCAD MCP servers
(notably `mixelpixx/KiCAD-MCP-Server`). They proved the demand but shared
recurring weaknesses: contradictory docs, an advertised-but-inert tool "router," a
fragile TypeScript↔Python bridge, heavy reliance on the SWIG `pcbnew` bindings —
which **KiCAD 11 removes** — and AI-generated designs **without mandatory
verification**.

Coppermind fixes each of these by construction and goes further: it turns a
*command executor* into an **engineering copilot** that reasons about the design,
verifies continuously, and keeps the human in control.

> 📄 The full analysis and architecture decisions live in
> [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

---

## ✨ What makes it different

| Pillar | What it means in practice |
| --- | --- |
| 🔌 **IPC-first** | Built on KiCAD's Protobuf IPC API via `kicad-python` (kipy) — the path that **survives KiCAD 11**, where SWIG is removed. SWIG is never the foundation. |
| 🐍 **One language** | Pure Python with the official MCP SDK (FastMCP). No TS↔Python bridge and its failure modes. |
| 🛡️ **Nothing is written blindly** | Every mutation flows through a transaction: `preview` (diff + render) → `verify` → `commit`/`rollback`, with `undo`/`redo`. |
| ✅ **Verification on the happy path** | Structural checks block invalid commits; **native KiCAD DRC/ERC joins the same gate**; every finding cites its rule. |
| 🧪 **KiCAD-independent core** | Domain + verification + transactions run and are **tested without KiCAD**. |
| 🔎 **Real progressive discovery** | A lean always-visible set; the long tail is discovered on demand. A **context-budget CI test** enforces it — not a slogan. |
| 🧠 **Design intelligence** | A **versioned, citable** EE knowledge base (IPC-2221 trace width, decoupling per IC…) powers proactive critique and design blocks — every suggestion points back to its rule. |
| 🤝 **Collaboration & pluggable integrations** | Versioned timeline, explain mode, suppliers (JLCPCB/LCSC), and a Freerouting autorouter — behind interfaces, with offline providers tested without a network. |
| 💾 **Persistent knowledge & state** | A **data-driven** EE rule base in YAML (`intelligence/ee_rules.yaml`); projects **saved/resumed** (JSON) and **exported to `.kicad_pcb`** for end-to-end headless DRC/render via the BatchBackend. |

---

## 🏗️ Architecture

The system is organized into **layers with sharp boundaries**. The **golden
rule**: `domain/` and `verification/` **never** import KiCAD — backends are the
only seam. This lets intelligence and verification be tested without KiCAD and lets
the backend be swapped (IPC today, IPC-only tomorrow) without touching the logic.

![Architecture](docs/architecture.svg)

| Layer | Folder | Responsibility |
| --- | --- | --- |
| Protocol | `server.py` | Tool/resource registration via FastMCP (thin layer) |
| Tools | `tools/` | `core` · `discovery` · `registry` · `routed` |
| Orchestration | `transactions/` | begin/preview/commit/rollback, undo/redo, timeline |
| Domain | `domain/` | board model, diff, operations (no KiCAD) |
| Verification | `verification/` | structural checks + severity (no KiCAD) |
| Intelligence | `intelligence/` | EE KB, critique, design blocks, placement |
| Schematic | `schematic/` | hierarchical sheets + netlist flattening |
| Variants | `variants.py` | per-component overrides (value/footprint/DNP) |
| Backends | `backends/` | IPC (kipy) · Batch (kicad-cli) · Memory (dev/CI) |
| Integrations | `integrations/` | suppliers · datasheets · Freerouting |

---

## 🔁 The transactional model

Every change follows the cycle:

```
begin → (apply to working copy) → preview → verify → commit | rollback
```

- **preview** returns a **structured diff**, a **render**, the **violations**
  (structural + native DRC), and design **advice** (cited).
- **commit** runs the **verification gate**. On an *error*-level violation the
  commit is **blocked** and the working copy is kept intact for fixing.
- Every successful commit enters the **timeline** and enables **undo/redo**.

The result: it is **structurally impossible** to write many invalid states unnoticed.

---

## 📦 Installation

Requirements: **Python 3.11+**, and (for live use) **KiCAD 10+** with the IPC API
enabled. No Node required.

```bash
git clone https://github.com/charlesmmorais/coppermind.git
cd coppermind

# dev environment (runs the whole suite WITHOUT needing KiCAD)
pip install -e ".[dev]"
pytest

# real use (MCP server) — add the [ipc] extra for live KiCAD
pip install -e ".[ipc]"
coppermind          # or: python -m coppermind.server
```

Backend selection via environment variable:

```bash
COPPERMIND_BACKEND=auto    # IPC if KiCAD is reachable, else memory (default)
COPPERMIND_BACKEND=ipc     # require live KiCAD
COPPERMIND_BACKEND=memory  # always in-memory (dev/offline)
```

---

## ⚙️ MCP client setup

Example for **Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "coppermind": {
      "command": "coppermind",
      "env": { "COPPERMIND_BACKEND": "auto", "LOG_LEVEL": "info" }
    }
  }
}
```

In KiCAD, enable the IPC API under **Preferences → Plugins → Enable IPC API Server**.

---

## 🧩 Backends

| Backend | Needs | load/apply | render | native DRC |
| --- | --- | --- | --- | --- |
| `MemoryBackend` | nothing | yes (in-memory) | SVG | — |
| `IPCBackend` | running KiCAD (or `headless=True`) | yes (kipy) | KiCAD SVG | via kicad-cli |
| `BatchBackend` | `kicad-cli` + a `.kicad_pcb` | (future phase) | KiCAD SVG | via kicad-cli |

Auto-detection order is **IPC → memory**. `BatchBackend` is file-specific, for
headless DRC/render.

---

## 🛠️ Tool catalog

**48 tools** total: **7 core** + **5 discovery** always visible, and **29 routed**
discovered on demand (across 8 categories).

### Always visible — core
`project_create` · `component_place` · `net_create` · `net_route` ·
`design_preview` · `design_commit` · `design_rollback`

### Always visible — progressive discovery
`list_tool_categories` · `get_category_tools` · `search_tools` ·
`get_tool_schema` · `execute_tool`

### Routed (on demand), by category

| Category | Tools |
| --- | --- |
| `component` | `component_move`, `component_edit`, `component_delete`, `component_list` |
| `net` | `net_list` |
| `board` | `board_info` |
| `design` | `design_undo`, `design_redo`, `design_render`, `design_critique`, `design_list_rules`, `design_explain_rule`, `design_add_decoupling`, `design_add_led`, `design_timeline`, `design_explain`, `design_placement_report` |
| `supplier` | `supplier_search`, `supplier_part`, `supplier_alternatives`, `supplier_cheapest` |
| `datasheet` | `datasheet_get`, `datasheet_enrich` |
| `routing` | `route_check`, `route_export_dsn`, `route_autoroute`, `route_import_ses` |
| `variant` | `variant_preview`, `variant_apply` |

> 💡 **Why this matters:** loading 41 schemas every turn wastes context and
> degrades model selection. Coppermind keeps the visible set lean and exposes the
> rest via `search_tools`/`execute_tool` — and a **CI test fails** if anyone blows
> the budget.

---

## 🧠 Design intelligence

What turns an "executor" into a "copilot" (all in `intelligence/`, no KiCAD):

- **Versioned, citable EE knowledge base** (`knowledge.py`): each rule has a stable
  id, a citation (e.g. **IPC-2221**), and a rationale. A governance test enforces
  unique ids and that every rule cites a source.
- **IPC-2221 calculator** (`trace_width.py`): minimum trace width for a current,
  validated against known tables (1 A ≈ 0.30 mm, 1 oz, 10 °C rise).
- **Proactive critique** (`critique.py`): power trace width, decoupling per IC,
  ground present — **advice** that **never blocks** the commit, each citing its
  rule. Surfaced as `advice` in `design_preview`.
- **Parametrizable design blocks** (`blocks.py`): decoupling capacitor, LED
  indicator — each returns a justified `BlockResult`.

```text
"Add a decoupling capacitor to U1"
→ design_add_decoupling(U1, C1)  →  the "U1 has no decoupling" advice disappears
```

---

## 🔀 Autorouting (Freerouting)

Full **Specctra DSN → SES → board** workflow, with runtime **Java direct, Docker,
or Podman** (auto-detected in that order).

![Freerouting flow](docs/freerouting-flow.svg)

👉 **Full step-by-step:** [`docs/AUTORROTEAMENTO.md`](docs/AUTORROTEAMENTO.md)
(export the DSN from KiCAD, download the jar / use Docker, run `route_autoroute`).

Summary:

```text
route_check                              # runtime + jar ready?
# export the DSN in KiCAD: File → Export → Specctra DSN
route_autoroute  dsn_path=... ses_path=...   # route and import
design_preview                           # review (diff + DRC + render)
design_commit                            # write (or design_rollback)
```

The **SES parser** (S-expression, resolution/unit-aware) and the board apply are
**pure and tested without Java**; only the engine run is isolated.

---

## 🛒 Suppliers (JLCPCB/LCSC) and datasheets

Two JLCPCB modes behind the same `SupplierProvider` interface:

1. **Public, no-credential API** — `JLCPCBProvider` (via JLCSearch), pure parser
   tested.
2. **Local catalog** — `LocalLibraryProvider` over the **`jlcparts` SQLite**
   (a **2.5M+ part** catalog), with search/price/stock/Basic/datasheet —
   **tested end-to-end** (SQLite is local, no network).

Plus **Basic-fee-aware cost optimization** (`pick_cheapest`): at low quantity the
Basic part wins (no $3 fee); at high volume the volume amortizes the fee.

**Datasheet enrichment via LCSC** (`integrations/datasheets.py`): resolve datasheet
URLs by LCSC id or for a BOM via the active provider, with a direct LCSC client
(pure response parser tested) as fallback.

```text
supplier_cheapest  query="10k 0603"  qty=100
datasheet_enrich   bom={ "R1": "C25804", "R2": "C22775" }
```

---

## 💬 Usage examples

All in natural language to the assistant:

```text
Create a project 'LEDBoard', 50x50mm.
Place an LED at 10,10 and a 330Ω resistor at 20,10.
Create net 'LED1' and route from R1 to the LED at 0.3mm.
Show me the preview and the design advice.
If it looks good, commit as "first LED".
```

```text
Find a cheaper Basic 10k 0603 resistor for 100 units.
Apply the low-cost variant: R1 = 22k, R2 = DNP.
Run the autorouter and show me what changed before writing.
```

> 🧪 **Runnable example:** the same LED flow, now via the Python API, lives in
> [`examples/led_board.py`](examples/led_board.py). It runs without KiCAD (MemoryBackend):
>
> ```bash
> python -m examples.led_board
> ```

---

## 🔬 Quality: tests & CI

- **132 tests** passing, **all without KiCAD or a network**. Live calls
  (IPC/CLI/network/external engine) are isolated and marked `# pragma: no cover`,
  covered by the CI **integration** job (KiCAD 10 + headless Java).
- **CI-enforced invariants**, not promises:
  - 🧮 **context budget**: fails if the visible tool set grows too large;
  - 📚 **KB governance**: every rule needs a unique id, a citation, and a rationale;
  - 🚫 **SWIG-free** (KiCAD 11 readiness): fails if any module imports `pcbnew`.

The IPC adapter is validated by a **fake-kipy harness** driven by **recorded
fixtures** (`tests/fixtures/`, `tests/conftest.py`): `load`/`apply`/`render` run
end-to-end with no KiCAD. The integration job runs the same paths against real
KiCAD (`tests/test_ipc_live.py`), and `scripts/record_kicad_fixture.py` captures
new fixtures from a real board.

```bash
pytest                 # full suite (no KiCAD)
ruff check src tests   # lint
mypy src               # typing
```

---

## 🗂️ Project layout

```
coppermind/
├── README.md                  # Portuguese (main)
├── README.en.md               # this file (English)
├── LICENSE                    # MIT
├── pyproject.toml
├── docs/
│   ├── ARQUITETURA.md         # architecture / decisions
│   ├── AUTORROTEAMENTO.md     # Freerouting step-by-step guide
│   ├── architecture.svg       # architecture diagram
│   └── freerouting-flow.svg   # autorouting flow diagram
├── src/coppermind/
│   ├── server.py · session.py
│   ├── domain/                # model, diff, operations (no KiCAD)
│   ├── verification/          # structural checks
│   ├── transactions/          # transactions + timeline
│   ├── intelligence/          # KB, critique, blocks, placement, explain
│   ├── schematic/             # hierarchy + netlist flattening
│   ├── variants.py
│   ├── backends/              # IPC · Batch · Memory · DRC · units · mapping
│   ├── integrations/          # suppliers · datasheets · freerouting
│   └── tools/                 # core · discovery · registry · routed
├── tests/                     # 132 tests (no KiCAD)
└── .github/workflows/ci.yml   # core (no KiCAD) + integration (KiCAD+Java)
```

---

## 🧭 Roadmap / phase status

| Phase | Theme | Status |
| --- | --- | --- |
| 0 | Foundation: domain, transactions, backends, core tools, CI | ✅ |
| 1 | Verification in the loop: real IPC, BatchBackend, native DRC/ERC, render | ✅ |
| 2 | Real progressive discovery + in-place edits in `plan_apply` | ✅ |
| 3 | Design intelligence: citable KB, IPC-2221, critique, blocks | ✅ |
| 4 | Collaboration & integrations: timeline, explain, suppliers, autorouter | ✅ |
| 5 | Maturity: hierarchical schematic, variants, placement, KiCAD 11 readiness | ✅ |

---

## ⚠️ Honest limitations

- **Live library footprint placement** depends on a stable kipy API to fetch the
  footprint *definition* — absent in kipy 0.7 / KiCAD 10. Coppermind already
  **models** it in the pure plan and attempts placement, logging anything unresolved.
- **Live track modify/remove**: tracks/vias now carry **stable ids** (UUID/KIID),
  so the plan and the IPC modify/remove path exist and are tested in the pure
  layer; live execution still awaits validation against real KiCAD.
- The official **`api.jlcpcb.com/Components`** API needs enterprise credentials —
  so the "no-credential" mode uses JLCSearch, and the local catalog covers the
  2.5M+ offline.

---

## 🤝 Contributing

Contributions welcome! Suggested flow:

1. Open an issue describing the bug/idea (with repro steps).
2. Fork → feature branch → keep the style (ruff/mypy) → **add tests**.
3. Ensure `pytest`, `ruff check`, and `mypy src` are green.
4. Open the PR with a clear description.

Non-negotiable principle: **the core stays KiCAD-independent and testable**.

---

## 📜 License & credits

Licensed under **MIT** — see [LICENSE](LICENSE).

**Credits:** [Model Context Protocol](https://modelcontextprotocol.io/) (Anthropic),
[KiCAD](https://www.kicad.org/), [kicad-python](https://docs.kicad.org/kicad-python-main/),
[Freerouting](https://github.com/freerouting/freerouting),
[jlcparts](https://github.com/yaqwsx/jlcparts) and
[JLCSearch](https://jlc
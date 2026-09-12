# Changelog

All notable changes to Coppermind are documented here.
This project follows [Semantic Versioning](https://semver.org/) and the
[Keep a Changelog](https://keepachangelog.com/) structure.

## [Unreleased]

### Added

- **Dual MCP transport** — the `coppermind` command now supports both
  `--transport stdio` and `--transport streamable-http`.
- **Loopback Streamable HTTP endpoint** — configurable host/port/path with defaults
  `127.0.0.1:8765/mcp`, intended for a trusted MCP tunnel/gateway.
- **Circuit IR** — semantic `Component`, `Pin`, `Net`, `PinRef` and `Constraint`
  models separate electrical intent from drawing coordinates.
- **Real KiCad symbol resolution** — support for installed/project `.kicad_sym`,
  unpacked `.kicad_symdir`, `sym-lib-table`, inherited symbols and real pin metadata.
- **Semantic MCP authoring tools** — `find_symbol`, `component_add`, `create_net`,
  `connect_pins` and `inspect_component` are part of the always-visible agent path.
- **Semantic Composer** — deterministic Circuit IR lowering to real KiCad schematic
  symbols, wires, labels and junctions.
- **KiCad ERC loop** — generated `.kicad_sch` files are checked with real
  `kicad-cli sch erc` when available, with structured feedback.
- **Visual Reviewer** — deterministic readability score, SVG/PDF export through
  KiCad, bounded reflow and optional multimodal critique.
- **Visual Auto-Fix** — typed Layout Action IR (`move_near`, `move_group`, `align`,
  `distribute`, `compact_block`, `separate_blocks`) with copy-on-write candidates,
  ERC diff, score gates and rollback.
- **Transport documentation** — Portuguese/English guides for stdio, Streamable HTTP,
  loopback security and remote MCP tunnelling.
- **Documentation index** under `docs/README.md`.

### Changed

- The primary agent interface is now **semantic**, not coordinate-driven.
- Raw schematic geometry primitives such as `symbol_add` and `wire_add` are hidden
  from the agent tool registry.
- Coordinate-level PCB operations remain available as routed compatibility tools.
- `project_create` initializes board + schematic + Circuit IR in one design context.
- Semantic state participates in preview/commit/rollback snapshots.
- Visual changes are rederived from Circuit IR and cannot silently change electrical
  connectivity.
- MCP Python SDK is explicitly pinned to the maintained FastMCP 1.x line
  (`mcp>=1.30,<2`) until a deliberate v2 migration is performed.
- KiCad integration CI is now blocking instead of `continue-on-error`.
- `README.md`, `README.en.md`, `docs/ARQUITETURA.md` and the architecture diagram were
  rewritten to match the implemented system.

### Removed

- **Generic two-pin schematic fallback.** An unresolved KiCad symbol now fails
  explicitly instead of creating a synthetic rectangle.
- The old assumption that KiCad schematic work must always be coordinate-authored by
  the LLM.

### Security

- Streamable HTTP refuses non-loopback binds. Coppermind must not be exposed directly
  on `0.0.0.0`/LAN/public interfaces in its current single-session design.
- HTTP remote access is expected to be mediated by an authenticated trusted MCP
  tunnel/gateway.
- Multimodal review remains opt-in; the data boundary is documented.
- Layout auto-fix remains geometry-only and checks Circuit IR invariance before
  accepting a candidate.

## [0.1.0] — Foundation

Initial foundation: KiCad-independent domain and verification, transactional
preview/diff/commit/rollback with undo/redo, IPC/Batch/Memory backends, progressive
tool discovery, EE knowledge rules, suppliers/datasheets, Freerouting, variants,
project persistence and `.kicad_pcb` serialization.

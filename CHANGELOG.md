# Changelog

All notable changes to Coppermind are documented here.
This project adheres to [Semantic Versioning](https://semver.org/) and
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Schematic (Eeschema) MVP** — drawable schematic model
  (`Schematic`/`SchSymbol`/`Wire`/`NetLabel`), an embedded symbol library
  (`schematic/symbols.py`, with a generic 2-pin fallback) and a `.kicad_sch`
  serializer (`serialize/kicad_sch.py`) that produces a self-contained file
  Eeschema opens. Tools: `schematic_create`, `symbol_add`, `wire_add`,
  `label_add`, `schematic_info`, `schematic_export_sch`. KiCAD's IPC API is
  PCB-only, so the schematic uses the same file-based path as the PCB export.
- **MCP server fix** — tool binding strips the injected `session` parameter from
  the public JSON schema (FastMCP could not serialize `Session`), fixing the
  "Server disconnected" startup crash; `IPCBackend` now tolerates kipy `KiCad()`
  constructor signature variants (no `headless` kwarg on newer versions).
- **Data-driven EE knowledge base** — rules live in `intelligence/ee_rules.yaml`
  (override via `COPPERMIND_RULES`); contributors extend design knowledge without
  touching code. Expanded to 7 cited rules (IPC-2221 trace width, decoupling per
  IC, ground present, differential-pair matching, annular ring, edge clearance,
  thermal relief).
- **Project persistence** — `persistence.py` with `save_board`/`load_board`
  (lossless JSON, stable ids preserved) and the `project_save` / `project_open`
  tools to save and resume a design.
- **`.kicad_pcb` serializer** — `serialize/kicad_pcb.py` (`board_to_kicad_pcb`)
  emits layers, nets, footprints-with-pads, segments, vias and the board outline.
  `BatchBackend.apply` now writes the board so kicad-cli can DRC/render it
  headlessly end-to-end. New `design_export_pcb` tool.
- **Pad/pin domain model** — `Pad` on `Component`, rotation-aware
  `pad_absolute_position`, pin-level netlist (`domain/netlist.py`), pad-aware DRC
  (`PAD_SHORT`, `SINGLE_PAD_NET`) and board-driven placement
  (`design_suggest_placement`); tools `component_add_pad`, `component_pads`,
  `design_netlist`.
- **Integration harness** — in-process fake of the kipy API driven by recorded
  fixtures (`tests/conftest.py`, `tests/fixtures/`) that exercises
  `IPCBackend.load/apply/render` with no KiCAD; `scripts/record_kicad_fixture.py`
  captures fixtures from a real board; `tests/test_ipc_live.py` runs the same
  paths against live KiCAD in the integration CI job.

### Changed
- **Stable item ids** — `Track`/`Via`/`Component` carry a stable `id` (UUID, or the
  KiCAD KIID when loaded). `plan_apply` and the diff are now matched by id, so
  reordering/mid-list inserts no longer produce phantom changes; live track
  modify/remove is wired via `update_items`/`remove_items_by_id`.
- **Freerouting timeout** — `FreeroutingRunner`/`autoroute_dsn` enforce a bounded
  timeout (`subprocess.TimeoutExpired` → clear `RuntimeError`); IPC DRC and batch
  subprocesses also time out.

### Security
- **Path validation** — `safety.py` (`validate_input_file`/`validate_output_path`)
  resolves `~`, follows symlinks and enforces extensions for tool file paths
  (`route_import_ses`, `route_autoroute`, `design_export_pcb`).

## [0.1.0] — Phases 0–5

Foundation through maturity: KiCAD-independent domain + verification, transactional
model (preview/diff/commit/rollback, undo/redo, timeline) with native DRC/ERC in
the commit gate, IPC/Batch/Memory backends, real progressive tool discovery,
citable design-intelligence (IPC-2221, critique, design blocks), collaboration and
pluggable integrations (suppliers JLCPCB/LCSC, datasheets, Freerouting), hierarchical
schematic netlist flattening, design variants, HPWL/barycenter placement, and a
SWIG-free guard for KiCAD 11 readiness.

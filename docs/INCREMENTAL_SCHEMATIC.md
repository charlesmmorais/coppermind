# Incremental schematic construction

CopperMind can build a schematic one semantic step at a time instead of recomputing the whole drawing after every component.

The incremental workflow is intended for an LLM/agent loop:

`add → place relative → connect + reroute changed net → checkpoint → render/export → next step`

## Principles

- Circuit IR remains the source of electrical intent.
- Relative placement is geometry-only: the agent says `right`, `left`, `above`, or `below`, never absolute sheet coordinates.
- Existing placed components are preserved while a new component is positioned relative to an anchor.
- A changed net is rerouted independently; unrelated incremental net geometry is preserved.
- `schematic_checkpoint` validates the current incremental geometry with semantic reference/routing checks and KiCad ERC, then snapshots the semantic state only when it is electrically non-blocking.
- `schematic_export_current` serializes the current incremental schematic without invoking the global semantic composer.
- The incremental actions are routed/discoverable tools, so the always-visible MCP surface stays within the context budget.

## Agent flow

Example:

1. `component_add(D1, Device:D, 1N4148)`
2. `component_add(R1, Device:R, 10k)`
3. discover `component_place_relative` and call `component_place_relative(R1, D1, right)`
4. `create_net(SIGNAL)`
5. discover/call `connect_incremental(SIGNAL, [D1.2, R1.1])`
6. `schematic_checkpoint()`
7. add the next component and repeat.

`connect_incremental` uses the same Circuit IR pin validation as `connect_pins`, then reroutes only the changed net in the drawable schematic.

`component_freeze_placement` can mark one or more accepted placements as stable metadata for the incremental authoring loop.

The existing global composer remains available for automatic whole-schematic layout. Incremental construction is deliberately a separate authoring path so a validated local arrangement is not destroyed by a later global BFS reflow.

## Current boundary

KiCad 10 does not yet provide the CopperMind backend with a live Eeschema mutation API, so this mode is pseudo-live: each semantic step updates the in-memory schematic, validates it, and can export the current `.kicad_sch`. When a live schematic IPC backend becomes available, the same semantic action loop can target it without changing Circuit IR.

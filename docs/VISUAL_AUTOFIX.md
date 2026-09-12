# Phase 5 — Visual Auto-Fix

Phase 5 turns Coppermind's visual reviewer into a **bounded geometry actuator**.
Electrical intent remains exclusively in Circuit IR. The auto-fix layer may move
schematic symbols and regenerate derived wires, labels and junctions; it may not
add/remove components, edit pins, create/delete nets or otherwise change
connectivity.

The behavior is independent of MCP transport: `stdio` and Streamable HTTP expose the
same routed tools. Transport setup and the HTTP security model are documented in
[TRANSPORTS.md](TRANSPORTS.md) / [TRANSPORTES.md](TRANSPORTES.md).

## Pipeline

```text
Circuit IR
   ↓
Phase-4 compose + visual review + optional multimodal critic
   ↓
Layout Action IR
   ↓
safety validation
   ↓
candidate schematic copy
   ↓
geometry-only execution
   ↓
reroute from unchanged Circuit IR
   ↓
visual review + optional multimodal review
   ↓
KiCad ERC
   ↓
accept candidate OR rollback
```

Candidates are copy-on-write. Rejected candidates never overwrite the working
schematic.

## Layout Action IR

Only these operations are accepted:

| Action | Purpose |
|---|---|
| `move_near` | Move one or more references near a target reference. |
| `move_group` | Move a group together near a target while preserving relative positions. |
| `align` | Align references horizontally or vertically. |
| `distribute` | Distribute 3+ references on one axis. |
| `compact_block` | Arrange a functional group into a bounded compact grid. |
| `separate_blocks` | Increase visual separation between references/groups. |

Example:

```json
{
  "type": "move_near",
  "refs": ["C7"],
  "target": "U3",
  "side": "right",
  "distance_mm": 5.08,
  "confidence": 0.94,
  "rationale": "Keep the decoupling capacitor visually associated with U3."
}
```

The executor validates component references against Circuit IR and the drawable
schematic before applying any action.

## Safety limits

- Maximum 6 actions per plan.
- Maximum 12 component references per action.
- Maximum 3 autonomous iterations.
- Maximum geometric displacement per component/action: 40.64 mm.
- All positions are snapped to the 2.54 mm schematic grid.
- Hard position constraints are honored (`fixed_position`, `lock_position`,
  `position_lock`, `do_not_move`).
- Circuit IR is serialized before/after the operation and must remain model-equivalent.
- Wires, labels and junctions are regenerated from Circuit IR after a move.
- Unknown or hallucinated component references are rejected.

## Acceptance gates

A candidate is accepted only when **all** gates pass:

1. The action produced a real geometry change.
2. There is no unresolved pin geometry.
3. Circuit IR is unchanged.
4. No new KiCad ERC violation was introduced.
5. No new blocking ERC state was introduced.
6. The deterministic visual score did not regress.
7. The combined visual score improved.

If any gate fails, the candidate copy is discarded.

## MCP tools

Phase-5 tools are deliberately **routed/discoverable**, not part of the default
always-visible tool budget.

### `schematic_visual_plan`

Runs the current visual pipeline and translates safe findings into a typed
`LayoutPlan`. It does not apply the plan.

### `schematic_visual_apply`

Accepts an explicit list of Layout Action IR dictionaries. It validates the plan,
applies it on a copy, reruns visual checks and ERC, and only publishes the geometry
when all acceptance gates pass.

### `schematic_visual_autofix`

Runs the bounded autonomous loop:

```text
review → plan → apply candidate → verify → accept/rollback
```

It stops when the target score is reached, no safe plan can be generated, a candidate
fails a gate, or 3 iterations have been attempted.

## Multimodal reviewer

The Phase-4 multimodal reviewer remains optional. Phase 5 consumes its normalized
findings and converts recognized visual issues (for example block grouping, density
and decoupling proximity) into Layout Action IR. Providers may also supply an
explicit action object, but it is still normalized and validated before execution.

The external model never receives a shell, Python executor or direct KiCad mutation
tool. See [MULTIMODAL_VISUAL_REVIEW.md](MULTIMODAL_VISUAL_REVIEW.md) for the provider
data boundary.

## Default design path

`design_preview` and `design_commit` **do not automatically invoke autonomous Phase-5
fixes**. They use the safer compose/review/ERC pipeline. Higher-autonomy auto-fix must
be requested explicitly through the routed tool.

This separation keeps normal design operations predictable and auditable while still
allowing an agent to request controlled iterative visual improvement.

## Transport and session note

When called through Streamable HTTP, auto-fix still acts on the single Coppermind
`Session` owned by that server process. Do not point multiple untrusted clients at the
same process; the HTTP mode is intended for one trusted design context behind a
local/tunnel boundary.

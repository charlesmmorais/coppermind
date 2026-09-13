# Incremental automatic placement

`component_place_auto` is the local-placement companion to the incremental schematic authoring loop.

Instead of asking the agent to choose an X/Y coordinate, CopperMind evaluates relative positions around an anchor component. By default it tries `right`, `below`, `above`, and `left` at the requested gap.

For each candidate CopperMind:

1. clones the current schematic state;
2. moves only the requested component;
3. clears only stale geometry owned by nets attached to that component;
4. routes every complete semantic net attached to the component, even if that net had no geometry yet;
5. rejects routing failures and excessively crowded placements;
6. scores the candidate using impacted-net route quality, drawing-envelope growth, and proximity to other component centers;
7. commits only the lowest-cost legal candidate.

Previously accepted unrelated nets are never rerouted by this operation.

The returned result includes the chosen direction and a summary for every attempted candidate so the agent can explain why a placement was selected.

## Preferred semantic-first flow

For a newly added component, declare electrical intent before materializing wires:

```text
component_add
    -> connect_pins        # Circuit IR only, no wire geometry
    -> component_place_auto
    -> schematic_checkpoint
    -> next component
```

This avoids routing a new component while it is still at the deterministic temporary position assigned by `component_add`. The auto placer evaluates the legal positions and materializes the affected nets only after the component has been moved on an isolated trial schematic.

`connect_incremental` remains useful when a component is already deliberately placed and the caller wants one changed net to be connected and routed atomically.

The global schematic composer is not invoked by this tool. `component_place_relative` remains available when the agent or user wants to force a specific semantic direction.

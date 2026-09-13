# Incremental automatic placement

`component_place_auto` is the local-placement companion to the incremental schematic authoring loop.

Instead of asking the agent to choose an X/Y coordinate, CopperMind evaluates relative positions around an anchor component. By default it tries `right`, `below`, `above`, and `left` at the requested gap.

For each candidate CopperMind:

1. clones the current schematic state;
2. moves only the requested component;
3. reroutes only already-routed nets connected to that component;
4. rejects routing failures and excessively crowded placements;
5. scores the candidate using impacted-net route quality, drawing-envelope growth, and proximity to other component centers;
6. commits only the lowest-cost legal candidate.

Previously accepted unrelated nets are never rerouted by this operation.

The returned result includes the chosen direction and a summary for every attempted candidate so the agent can explain why a placement was selected.

Typical incremental flow:

```text
component_add
    -> connect_incremental
    -> component_place_auto
    -> schematic_checkpoint
    -> next component
```

The global schematic composer is not invoked by this tool. `component_place_relative` remains available when the agent or user wants to force a specific semantic direction.
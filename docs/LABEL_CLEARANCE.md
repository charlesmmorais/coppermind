# Net-label clearance

CopperMind keeps net labels electrically attached to their own wire network while choosing a readable anchor and text side.

## Goals

The label-placement pass is geometry-only. It must not create or remove components, pins, nets, wires, or junctions, and it must not move the label anchor off its connected wire network.

For each label, the serializer:

1. identifies the connected wire component that contains the current label anchor;
2. builds candidate anchors on the same connected wire segments;
3. evaluates left/right and top/bottom text justification at those anchors;
4. penalizes collisions with visible `Reference`/`Value` fields, component bodies, labels already placed, unrelated wires, and junctions;
5. chooses the lowest-penalty deterministic placement, preferring positions closer to the original semantic anchor when penalties tie.

## Safety

- electrical connectivity is unchanged;
- label anchors remain on the same wire network;
- crossings between unrelated wires are not treated as connectivity unless a wire endpoint actually joins the other segment;
- hidden generated references such as `#PWR*` and `#FLG*` do not reserve text clearance;
- placement is deterministic for the same schematic geometry.

## Complex-circuit behavior

The pass is intended for denser circuits where a midpoint label such as `VOUT`, `DATA_OUT`, or `SENSE_A` could otherwise overlap component fields or a crossing signal. Adjacent labels are placed sequentially and reserve their text boxes so later labels avoid the already occupied region.

This first implementation performs clearance during KiCad serialization. It therefore changes the final rendered `.kicad_sch` without changing Circuit IR or the semantic net topology.

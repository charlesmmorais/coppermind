# Schematic field clearance

This note defines the field-placement pass for `Reference` and `Value` labels emitted into KiCad schematics.

## Goals

- keep `Reference` and `Value` aligned as a pair;
- keep visible fields off symbol bodies and primary wires;
- preserve conventional power-symbol placement;
- hide special references such as `#PWR*` and `#FLG*`;
- change only serialized field geometry, never Circuit IR or electrical connectivity.

## Rules

- Vertical two-pin symbols: place both fields to the right, left-justified, at a 5.08 mm horizontal clearance from the symbol center. Stack `Reference` above `Value` with 2.54 mm separation.
- Horizontal two-pin symbols: center fields on the symbol X axis, with `Reference` 5.08 mm above and `Value` 5.08 mm below.
- Other non-power symbols: use the same 5.08 mm top/bottom clearance as a safe generic fallback.
- Power symbols: preserve their conventional value position while keeping special references hidden.

The change is deliberately serializer-only: pin anchors, wires, nets, ERC semantics and Circuit IR are unchanged.

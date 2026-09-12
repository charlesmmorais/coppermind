# Layout polish

This document defines the next visual-quality pass after the semantic compact power-chain layout merged in PR #8.

## Goal

Improve schematic readability without changing Circuit IR or electrical connectivity.

## Initial acceptance criteria

1. **Shorter PWR_FLAG branches**
   - Target horizontal offset from the functional rail: **15.24 mm** (6 × 2.54 mm), reduced from 25.4 mm.
   - Keep the flag on the same electrical Y coordinate as the rail node.
   - Preserve exact pin anchors and KiCad ERC connectivity.

2. **Field clearance**
   - `Reference` and `Value` must not overlap symbol bodies, wires, junctions, or power glyphs.
   - Special references (`#PWR*`, `#FLG*`) remain hidden.

3. **Net-label alignment**
   - Signal labels such as `VOUT` should sit near the middle of their primary segment and avoid component fields.
   - Named power symbols should not receive redundant textual net labels.

4. **Compactness**
   - Simple power-bounded two-pin chains remain vertical and centered.
   - Avoid unnecessary whitespace while retaining enough room for fields and branches.

5. **Safety gates**
   - Circuit IR must remain byte-for-byte equivalent before/after geometry optimization.
   - KiCad ERC must remain non-blocking.
   - Existing anchor regression tests must continue to pass.
   - Visual review score must not regress.

## Reference case

Use the validated divider from PR #8 as the first regression fixture:

```text
+5V
 |
PWR_FLAG -- rail -- R1 10k
                 |
                VOUT
                 |
                R2 10k
                 |
PWR_FLAG -- rail -- GND
```

The first implementation step in this PR is to shorten the two `PWR_FLAG` branches while preserving the layout and ERC behavior already validated in KiCad 10.

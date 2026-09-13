# Dense auto-placement validation notes

Local KiCad validation of `dense_auto_placement.kicad_sch` showed that the semantic-first auto-placement is electrically stable, but the placement scorer still permits candidates outside the useful sheet area. In the validated example, `R7` and `R8` reached approximately y=-1.27 mm and `R9` reached approximately y=-26.67 mm, placing the upper branch beyond the drawing-sheet border.

The next scorer revision should therefore treat sheet-margin violations as hard candidate rejection and evaluate multiple gap distances around an anchor, not only one caller-provided distance. Visual compactness should be optimized only among candidates that stay inside the usable sheet rectangle and preserve foreign-net separation.

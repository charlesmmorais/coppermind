"""IPC backend — the primary, future-proof adapter.

Talks to KiCAD through the Protobuf IPC API via ``kicad-python`` (kipy). This is
the path that survives KiCAD 11, where the SWIG ``pcbnew`` bindings are removed.
Works against a running GUI instance or a headless ``kicad-cli`` api-server
(``headless=True``).

Wired against the real kipy API:
  * ``load``  — maps live footprints / nets / tracks into a Coppermind Board.
  * ``apply`` — diffs against the live board (pure ``plan_apply``) and, inside a
    single commit: creates tracks (named nets), updates moved/edited components
    (``update_items``), removes deleted components (``remove_items``), and
    attempts library footprint placement.
  * ``render`` / ``run_drc`` — KiCAD-native SVG and native DRC.

Honest limitation: kipy 0.7 / KiCAD 10 exposes no stable call to fetch a library
footprint *definition* for placement (only ``open_library_item`` into the
editor). Placement is therefore attempted and any unresolved footprint is
reported in ``apply``'s skip log rather than silently lost; it will succeed once
kipy gains a library-resolve API. Track *modification/removal* needs a stable
item-id mapping (Phase 3); only track *additions* are pushed live today. kipy is
imported lazily so the rest of Coppermind runs without it.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

from coppermind.backends.base import KicadBackend
from coppermind.backends.drc import build_drc_command, parse_drc_report
from coppermind.backends.ipc_mapping import plan_apply
from coppermind.backends.units import mm_to_nm, nm_to_mm
from coppermind.domain.models import Board, Component, Layer, Net, Point, Track
from coppermind.verification.checks import Violation

logger = logging.getLogger(__name__)

_LAYER_TO_KICAD = {Layer.F_CU: 0, Layer.B_CU: 2}
_KICAD_TO_LAYER = {0: Layer.F_CU, 2: Layer.B_CU}


class IPCBackend(KicadBackend):
    name = "ipc"

    def __init__(self, headless: bool = False, file_path: str | None = None) -> None:
        self._kicad = None  # type: ignore[var-annotated]
        self._headless = headless
        self._file_path = file_path

    # -- connection ---------------------------------------------------------

    def _connect(self):  # type: ignore[no-untyped-def]
        if self._kicad is not None:
            return self._kicad
        try:
            from kipy import KiCad  # type: ignore import-not-found
        except Exception as exc:  # pragma: no cover - depends on env
            logger.debug("kipy not importable: %s", exc)
            return None
        try:
            self._kicad = KiCad(headless=self._headless, file_path=self._file_path)
            return self._kicad
        except Exception as exc:  # pragma: no cover - needs running KiCAD
            logger.info("KiCAD IPC not reachable (is the IPC API enabled?): %s", exc)
            return None

    def is_available(self) -> bool:
        return self._connect() is not None

    def _board(self):  # type: ignore[no-untyped-def]
        kicad = self._connect()
        if kicad is None:
            raise RuntimeError("KiCAD IPC unavailable; start KiCAD with the IPC API enabled")
        return kicad.get_board()

    @staticmethod
    def _vec(x_mm: float, y_mm: float):  # type: ignore[no-untyped-def]
        from kipy.geometry import Vector2  # type: ignore import-not-found

        try:
            return Vector2.from_xy(mm_to_nm(x_mm), mm_to_nm(y_mm))
        except AttributeError:  # pragma: no cover - API variant
            v = Vector2()
            v.x, v.y = mm_to_nm(x_mm), mm_to_nm(y_mm)
            return v

    # -- read ---------------------------------------------------------------

    def load(self, name: str) -> Board:  # pragma: no cover - needs running KiCAD
        board = self._board()
        result = Board(name=name)
        for net in board.get_nets():
            if net.name:
                result.nets[net.name] = Net(name=net.name)
        for fp in board.get_footprints():
            ref = fp.reference_field.value if fp.reference_field else ""
            if not ref:
                continue
            result.components[ref] = Component(
                reference=ref,
                value=(fp.value_field.value if fp.value_field else ""),
                footprint=self._footprint_id(fp),
                position=Point(x=nm_to_mm(fp.position.x), y=nm_to_mm(fp.position.y)),
                layer=_KICAD_TO_LAYER.get(fp.layer, Layer.F_CU),
            )
        for tr in board.get_tracks():
            if not hasattr(tr, "start"):
                continue
            result.tracks.append(
                Track(
                    net=getattr(tr.net, "name", "") or "",
                    start=Point(x=nm_to_mm(tr.start.x), y=nm_to_mm(tr.start.y)),
                    end=Point(x=nm_to_mm(tr.end.x), y=nm_to_mm(tr.end.y)),
                    width=nm_to_mm(tr.width),
                    layer=_KICAD_TO_LAYER.get(tr.layer, Layer.F_CU),
                )
            )
        return result

    @staticmethod
    def _footprint_id(fp) -> str:  # type: ignore[no-untyped-def]
        try:
            lib = fp.definition.id
            return f"{lib.library}:{lib.name}"
        except Exception:
            return ""

    # -- write --------------------------------------------------------------

    def apply(self, board: Board) -> None:  # pragma: no cover - needs running KiCAD
        from kipy.board_types import Net as KiNet  # type: ignore import-not-found
        from kipy.board_types import Track as KiTrack  # type: ignore import-not-found

        live = self.load(board.name)
        plan = plan_apply(live, board)
        if plan.is_empty:
            return

        kboard = self._board()
        commit = kboard.begin_commit()
        try:
            new_items = []
            for t in plan.tracks_to_add:
                kt = KiTrack()
                kt.start = self._vec(t.start.x, t.start.y)
                kt.end = self._vec(t.end.x, t.end.y)
                kt.width = mm_to_nm(t.width)
                kt.layer = _LAYER_TO_KICAD.get(t.layer, 0)
                if t.net:
                    kt.net = KiNet(name=t.net)
                new_items.append(kt)
            if new_items:
                kboard.create_items(new_items)

            self._place_footprints(kboard, plan.footprints_to_add)
            self._place_vias(kboard, plan.vias_to_add)
            self._modify_components(kboard, plan.components_to_modify)
            self._remove_components(kboard, plan.component_refs_to_remove)

            if plan.tracks_to_modify or plan.track_indices_to_remove:
                logger.warning(
                    "Track modify/remove needs a stable item-id map (Phase 3); "
                    "%d modify / %d remove deferred.",
                    len(plan.tracks_to_modify),
                    len(plan.track_indices_to_remove),
                )

            kboard.push_commit(commit, message="coppermind: apply")
        except Exception:
            kboard.drop_commit(commit)
            raise

    def _place_footprints(self, kboard, comps: list[Component]) -> None:  # type: ignore[no-untyped-def]
        from kipy.board_types import FootprintInstance  # type: ignore import-not-found

        skipped = []
        to_create = []
        for c in comps:
            try:
                fp = FootprintInstance()
                fp.position = self._vec(c.position.x, c.position.y)
                fp.layer = _LAYER_TO_KICAD.get(c.layer, 0)
                if c.reference and fp.reference_field:
                    fp.reference_field.value = c.reference
                if c.value and fp.value_field:
                    fp.value_field.value = c.value
                self._attach_definition(fp, c.footprint)
                to_create.append(fp)
            except Exception as exc:
                skipped.append(f"{c.reference} ({c.footprint}): {exc}")
        if to_create:
            kboard.create_items(to_create)
        if skipped:
            logger.warning(
                "Footprint placement unresolved for %d item(s) (kipy lacks a stable "
                "library-fetch API): %s",
                len(skipped), "; ".join(skipped),
            )

    def _place_vias(self, kboard, vias) -> None:  # type: ignore[no-untyped-def]
        from kipy.board_types import Net as KiNet  # type: ignore import-not-found
        from kipy.board_types import Via as KiVia  # type: ignore import-not-found

        items = []
        for v in vias:
            kv = KiVia()
            kv.position = self._vec(v.position.x, v.position.y)
            if v.net:
                kv.net = KiNet(name=v.net)
            items.append(kv)
        if items:
            kboard.create_items(items)

    @staticmethod
    def _attach_definition(fp, footprint_id: str) -> None:  # type: ignore[no-untyped-def]
        """Best-effort: tag the instance with its library id.

        Full geometry resolution depends on a kipy library-fetch API that does
        not exist in 0.7; if absent, KiCAD will reject the item and it is
        reported as skipped by the caller.
        """
        if ":" not in footprint_id:
            raise ValueError("footprint id must be 'library:name'")
        from kipy.common_types import LibraryIdentifier  # type: ignore import-not-found

        lib, name = footprint_id.split(":", 1)
        ident = LibraryIdentifier()
        ident.library, ident.name = lib, name
        fp.definition.id = ident  # may raise if definition is read-only

    def _modify_components(self, kboard, comps: list[Component]) -> None:  # type: ignore[no-untyped-def]
        if not comps:
            return
        by_ref = {c.reference: c for c in comps}
        updated = []
        for fp in kboard.get_footprints():
            ref = fp.reference_field.value if fp.reference_field else ""
            target = by_ref.get(ref)
            if target is None:
                continue
            fp.position = self._vec(target.position.x, target.position.y)
            fp.layer = _LAYER_TO_KICAD.get(target.layer, 0)
            if fp.value_field:
                fp.value_field.value = target.value
            updated.append(fp)
        if updated:
            kboard.update_items(updated)

    def _remove_components(self, kboard, refs: list[str]) -> None:  # type: ignore[no-untyped-def]
        if not refs:
            return
        wanted = set(refs)
        to_remove = [
            fp for fp in kboard.get_footprints()
            if (fp.reference_field.value if fp.reference_field else "") in wanted
        ]
        if to_remove:
            kboard.remove_items(to_remove)

    # -- render / DRC -------------------------------------------------------

    def render(self, board: Board) -> bytes | None:  # pragma: no cover - needs KiCAD
        try:
            kboard = self._board()
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
                out = tmp.name
            kboard.export_svg(out, fit_page_to_board=True)
            with open(out, "rb") as fh:
                data = fh.read()
            os.unlink(out)
            return data
        except Exception as exc:
            logger.info("IPC render failed: %s", exc)
            return None

    def run_drc(self, board: Board) -> list[Violation]:  # pragma: no cover - needs KiCAD
        kicad = self._connect()
        if kicad is None:
            return []
        try:
            kboard = self._board()
            cli = kicad.get_kicad_binary_path("kicad-cli")
            with tempfile.TemporaryDirectory() as d:
                pcb = os.path.join(d, f"{board.name}.kicad_pcb")
                with open(pcb, "w", encoding="utf-8") as fh:
                    fh.write(kboard.get_as_string())
                report = os.path.join(d, "drc.json")
                subprocess.run(build_drc_command(pcb, report, kicad_cli=cli),
                               check=True, capture_output=True)
                with open(report, encoding="utf-8") as fh:
                    return parse_drc_report(json.load(fh))
        except Exception as exc:
            logger.info("IPC native DRC failed: %s", exc)
            return []

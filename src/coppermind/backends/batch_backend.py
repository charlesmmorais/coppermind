"""Headless batch backend (file-based) using ``kicad-cli``.

Complements IPC: where IPC needs a running KiCAD, the batch backend verifies and
renders an existing ``.kicad_pcb`` file with no GUI — ideal for CI and for
DRC-gating exported boards. ``run_drc`` and ``render`` are fully functional
(subprocess + pure parsers from ``backends.drc``). ``apply`` writes the board to
the .kicad_pcb via the pure serializer, so a Coppermind board can be DRC'd and
rendered headlessly; ``load`` (parsing .kicad_pcb back) remains a later deliverable.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile

from coppermind.backends.base import KicadBackend
from coppermind.backends.drc import build_drc_command, parse_drc_report
from coppermind.serialize import board_to_kicad_pcb
from coppermind.domain.models import Board
from coppermind.verification.checks import Violation

logger = logging.getLogger(__name__)


class BatchBackend(KicadBackend):
    name = "batch"

    def __init__(self, pcb_path: str, kicad_cli: str = "kicad-cli") -> None:
        self.pcb_path = pcb_path
        self.kicad_cli = kicad_cli

    def is_available(self) -> bool:
        return shutil.which(self.kicad_cli) is not None and os.path.exists(self.pcb_path)

    def load(self, name: str) -> Board:
        raise NotImplementedError("BatchBackend.load needs a .kicad_pcb parser (later phase)")

    def apply(self, board: Board) -> None:
        """Serialize the board to ``self.pcb_path`` so kicad-cli can act on it."""
        from pathlib import Path

        target = Path(self.pcb_path).expanduser()
        if not target.parent.exists():
            raise FileNotFoundError(f"output directory does not exist: {target.parent}")
        target.write_text(board_to_kicad_pcb(board), encoding="utf-8")

    def render(self, board: Board) -> bytes | None:
        try:
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "board.svg")
                cmd = [
                    self.kicad_cli, "pcb", "export", "svg",
                    "--output", out, "--fit-page-to-board", self.pcb_path,
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=300)
                with open(out, "rb") as fh:
                    return fh.read()
        except Exception as exc:  # pragma: no cover - needs kicad-cli
            logger.info("batch render failed: %s", exc)
            return None

    def run_drc(self, board: Board) -> list[Violation]:
        try:
            with tempfile.TemporaryDirectory() as d:
                report = os.path.join(d, "drc.json")
                cmd = build_drc_command(self.pcb_path, report, kicad_cli=self.kicad_cli)
                subprocess.run(cmd, check=True, capture_output=True, timeout=300)
                with open(report, encoding="utf-8") as fh:
                    return parse_drc_report(json.load(fh))
        except Exception as exc:  # pragma: no cover - needs kicad-cli
            logger.info("batch DRC failed: %s", exc)
            return []

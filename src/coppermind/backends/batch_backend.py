"""Headless batch backend (file-based) using ``kicad-cli``.

Complements IPC: where IPC needs a running KiCAD, the batch backend verifies and
renders an existing ``.kicad_pcb`` file with no GUI — ideal for CI and for
DRC-gating exported boards. ``run_drc`` and ``render`` are fully functional
(subprocess + pure parsers from ``backends.drc``); ``load``/``apply`` require a
.kicad_pcb (de)serializer, which is a later deliverable, so they raise clearly.
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
        raise NotImplementedError("BatchBackend.apply needs a .kicad_pcb writer (later phase)")

    def render(self, board: Board) -> bytes | None:
        try:
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "board.svg")
                cmd = [
                    self.kicad_cli, "pcb", "export", "svg",
                    "--output", out, "--fit-page-to-board", self.pcb_path,
                ]
                subprocess.run(cmd, check=True, capture_output=True)
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
                subprocess.run(cmd, check=True, capture_output=True)
                with open(report, encoding="utf-8") as fh:
                    return parse_drc_report(json.load(fh))
        except Exception as exc:  # pragma: no cover - needs kicad-cli
            logger.info("batch DRC failed: %s", exc)
            return []

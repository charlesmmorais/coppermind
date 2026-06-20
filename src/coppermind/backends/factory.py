"""Backend auto-detection.

Order of preference mirrors the architecture: IPC first (future-proof, live UI),
then the in-memory backend as a guaranteed fallback for dev/offline/CI. A
BatchBackend (kicad-cli, headless) slots in here in Phase 1.

Override with the ``COPPERMIND_BACKEND`` env var: ``auto`` | ``ipc`` | ``memory``.
"""

from __future__ import annotations

import logging
import os

from coppermind.backends.base import KicadBackend
from coppermind.backends.memory_backend import MemoryBackend

logger = logging.getLogger(__name__)


def create_backend(preference: str | None = None) -> KicadBackend:
    pref = (preference or os.environ.get("COPPERMIND_BACKEND", "auto")).lower()

    if pref == "memory":
        return MemoryBackend()

    if pref in ("auto", "ipc"):
        try:
            from coppermind.backends.ipc_backend import IPCBackend

            ipc = IPCBackend()
            if ipc.is_available():
                logger.info("Using IPC backend (live KiCAD).")
                return ipc
        except Exception as exc:  # pragma: no cover - env dependent
            logger.debug("IPC backend unavailable: %s", exc)
        if pref == "ipc":
            raise RuntimeError("IPC backend requested but KiCAD IPC is not reachable")

    logger.info("Using in-memory backend (no live KiCAD).")
    return MemoryBackend()

"""The single seam between Coppermind and KiCAD.

Every concrete backend (IPC, batch/headless, in-memory) implements this port.
Because the domain and verification layers depend only on this interface, the
project is ready for the KiCAD 11 world where the SWIG bindings are gone and IPC
is the only supported API — we just swap the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from coppermind.domain.models import Board
from coppermind.verification.checks import Violation


class KicadBackend(ABC):
    """Persist/inspect a board. Implementations must be side-effect-safe on read."""

    #: Short identifier, e.g. "ipc", "batch", "memory".
    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this backend can be used in the current environment."""

    @abstractmethod
    def load(self, name: str) -> Board:
        """Load (or initialize) a board document by name/path."""

    @abstractmethod
    def apply(self, board: Board) -> None:
        """Persist the full board state. Called only after verification passes."""

    @abstractmethod
    def render(self, board: Board) -> bytes | None:
        """Return a PNG/SVG preview of the board, or None if unsupported."""

    def run_drc(self, board: Board) -> list[Violation]:
        """Run native KiCAD DRC/ERC if the backend supports it. Default: none.

        Returns native violations to be merged into the verification loop. A
        backend without native DRC returns an empty list (Coppermind's own
        structural checks still run).
        """
        return []

"""Transactional document model.

Nothing is ever written blindly. Mutations land on a working copy inside a
transaction; the caller can `preview` (diff + verification) before `commit`.
Commit runs verification (Coppermind structural checks merged with native KiCAD
DRC) and only persists to the backend if no blocking violation exists; otherwise
it returns the violations and leaves the working copy intact so the caller can
fix and retry. Every successful commit pushes a snapshot so `undo` is always
available.
"""

from __future__ import annotations

from pydantic import BaseModel

from coppermind.backends.base import KicadBackend
from coppermind.domain.diff import BoardDiff, diff_boards
from coppermind.domain.models import Board
from coppermind.verification.checks import Violation, has_blocking, verify


class NoActiveTransactionError(RuntimeError):
    pass


class Transaction:
    """A working copy plus the base it was branched from."""

    def __init__(self, base: Board) -> None:
        self._base = base
        self.working = base.copy_deep()

    def diff(self) -> BoardDiff:
        return diff_boards(self._base, self.working)


class CommitResult(BaseModel):
    committed: bool
    diff: BoardDiff
    violations: list[Violation]

    def summary(self) -> str:
        head = "committed" if self.committed else "blocked"
        errs = [v.label() for v in self.violations]
        tail = (" | " + "; ".join(errs)) if errs else ""
        return f"{head}: {self.diff.summary()}{tail}"


class TimelineEntry(BaseModel):
    """One committed step in the versioned timeline (an append-only audit log)."""

    step: int
    label: str
    summary: str
    components: int
    nets: int
    tracks: int


class Document:
    """Owns the committed board, the active transaction, and undo history."""

    def __init__(
        self,
        board: Board,
        backend: KicadBackend,
        max_history: int = 50,
        run_native_drc: bool = True,
    ) -> None:
        self.board = board
        self.backend = backend
        self.run_native_drc = run_native_drc
        self._active: Transaction | None = None
        self._history: list[Board] = []
        self._redo: list[Board] = []
        self._max_history = max_history
        self._timeline: list[TimelineEntry] = []
        self._step = 0

    def _verify_all(self, board: Board) -> list[Violation]:
        """Coppermind structural/advisory checks merged with native KiCAD DRC."""
        violations = verify(board)
        if self.run_native_drc:
            violations = violations + self.backend.run_drc(board)
        return sorted(violations, key=lambda v: v.severity, reverse=True)

    # -- transaction lifecycle ---------------------------------------------

    @property
    def has_active(self) -> bool:
        return self._active is not None

    def begin(self) -> Transaction:
        if self._active is None:
            self._active = Transaction(self.board)
        return self._active

    def working(self) -> Board:
        """Working board of the active transaction (auto-begins one)."""
        return self.begin().working

    def preview(self) -> tuple[BoardDiff, list[Violation]]:
        if self._active is None:
            return diff_boards(self.board, self.board), []
        return self._active.diff(), self._verify_all(self._active.working)

    def commit(self, label: str = "") -> CommitResult:
        if self._active is None:
            raise NoActiveTransactionError("no active transaction to commit")
        working = self._active.working
        violations = self._verify_all(working)
        if has_blocking(violations):
            return CommitResult(committed=False, diff=self._active.diff(), violations=violations)

        diff = self._active.diff()
        # Snapshot current committed state for undo, then advance.
        self._push_history(self.board)
        self.board = working
        self.backend.apply(self.board)
        self._active = None
        self._redo.clear()
        self._record_timeline(label or "commit", diff.summary())
        return CommitResult(committed=True, diff=diff, violations=violations)

    def rollback(self) -> None:
        self._active = None

    # -- undo / redo --------------------------------------------------------

    def undo(self) -> bool:
        if not self._history:
            return False
        self._redo.append(self.board)
        self.board = self._history.pop()
        self.backend.apply(self.board)
        self._active = None
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._push_history(self.board)
        self.board = self._redo.pop()
        self.backend.apply(self.board)
        self._active = None
        return True

    # -- versioned timeline -------------------------------------------------

    def _record_timeline(self, label: str, summary: str) -> None:
        self._step += 1
        self._timeline.append(
            TimelineEntry(
                step=self._step,
                label=label,
                summary=summary,
                components=len(self.board.components),
                nets=len(self.board.nets),
                tracks=len(self.board.tracks),
            )
        )

    def timeline(self) -> list[TimelineEntry]:
        return list(self._timeline)

    def _push_history(self, board: Board) -> None:
        self._history.append(board.copy_deep())
        if len(self._history) > self._max_history:
            self._history.pop(0)

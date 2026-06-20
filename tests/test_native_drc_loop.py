"""Native DRC/ERC must participate in the commit gate, not just our own checks.

We use a fake backend whose run_drc returns a canned native violation, proving
the transaction loop merges native findings and blocks commits on native errors.
"""

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.domain import operations as ops
from coppermind.transactions.manager import Document
from coppermind.verification.checks import Severity, Violation


class FakeDrcBackend(MemoryBackend):
    name = "fake-drc"

    def __init__(self, severity: Severity) -> None:
        super().__init__()
        self._severity = severity

    def run_drc(self, board):
        return [
            Violation(
                severity=self._severity,
                code="DRC:clearance",
                message="native clearance violation",
                rule="KiCAD DRC (clearance)",
            )
        ]


def _doc(backend, run_native_drc=True):
    board = ops.create_board("demo", 50, 40)
    backend.apply(board)
    return Document(board, backend, run_native_drc=run_native_drc)


def test_native_error_blocks_commit():
    doc = _doc(FakeDrcBackend(Severity.ERROR))
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)  # structurally valid
    result = doc.commit()
    assert not result.committed
    assert any(v.code == "DRC:clearance" for v in result.violations)


def test_native_warning_does_not_block():
    doc = _doc(FakeDrcBackend(Severity.WARNING))
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    result = doc.commit()
    assert result.committed
    # warning still surfaced in the report
    assert any(v.code == "DRC:clearance" for v in result.violations)


def test_native_drc_can_be_disabled():
    doc = _doc(FakeDrcBackend(Severity.ERROR), run_native_drc=False)
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    result = doc.commit()
    assert result.committed
    assert not any(v.code == "DRC:clearance" for v in result.violations)


def test_preview_includes_native_violations():
    doc = _doc(FakeDrcBackend(Severity.ERROR))
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    _diff, violations = doc.preview()
    assert any(v.code == "DRC:clearance" for v in violations)

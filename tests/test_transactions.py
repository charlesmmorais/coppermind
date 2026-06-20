import pytest

from coppermind.backends.memory_backend import MemoryBackend
from coppermind.domain import operations as ops
from coppermind.transactions.manager import Document, NoActiveTransactionError


def make_doc():
    backend = MemoryBackend()
    board = ops.create_board("demo", 50, 40)
    backend.apply(board)
    return Document(board, backend), backend


def test_changes_are_invisible_until_commit():
    doc, backend = make_doc()
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    # committed board untouched; backend store untouched
    assert "R1" not in doc.board.components
    assert "R1" not in backend.load("demo").components


def test_preview_shows_diff_without_persisting():
    doc, backend = make_doc()
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    diff, violations = doc.preview()
    assert diff.components_added == ["R1"]
    assert "R1" not in doc.board.components


def test_commit_persists_and_clears_transaction():
    doc, backend = make_doc()
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    result = doc.commit()
    assert result.committed
    assert "R1" in doc.board.components
    assert "R1" in backend.load("demo").components
    assert not doc.has_active


def test_commit_blocked_by_error_keeps_working_copy():
    doc, _ = make_doc()
    ops.add_component(doc.working(), "R1", "R_0805", 999, 999)  # outside outline
    result = doc.commit()
    assert not result.committed
    assert any(v.code == "COMPONENT_OUTSIDE_BOARD" for v in result.violations)
    assert "R1" not in doc.board.components  # not persisted
    assert doc.has_active  # still open so user can fix


def test_fix_then_commit_after_block():
    doc, _ = make_doc()
    ops.add_component(doc.working(), "R1", "R_0805", 999, 999)
    assert not doc.commit().committed
    ops.move_component(doc.working(), "R1", 10, 10)  # fix
    assert doc.commit().committed


def test_rollback_discards_changes():
    doc, _ = make_doc()
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    doc.rollback()
    assert not doc.has_active
    assert "R1" not in doc.board.components


def test_undo_redo_round_trip():
    doc, backend = make_doc()
    ops.add_component(doc.working(), "R1", "R_0805", 10, 10)
    doc.commit()
    assert doc.undo() is True
    assert "R1" not in doc.board.components
    assert "R1" not in backend.load("demo").components
    assert doc.redo() is True
    assert "R1" in doc.board.components


def test_commit_without_transaction_raises():
    doc, _ = make_doc()
    with pytest.raises(NoActiveTransactionError):
        doc.commit()

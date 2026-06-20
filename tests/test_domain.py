from coppermind.domain import operations as ops
from coppermind.domain.diff import diff_boards
from coppermind.domain.models import Board, BoardOutline, Point


def test_create_board_has_outline():
    board = ops.create_board("demo", 50, 40)
    assert board.outline == BoardOutline(width=50, height=40)


def test_add_component_rejects_duplicate():
    board = ops.create_board("demo", 50, 40)
    ops.add_component(board, "R1", "R_0805", 10, 10)
    try:
        ops.add_component(board, "R1", "R_0805", 20, 20)
    except ValueError as e:
        assert "already exists" in str(e)
    else:
        raise AssertionError("expected ValueError on duplicate reference")


def test_move_component_updates_position():
    board = ops.create_board("demo", 50, 40)
    ops.add_component(board, "R1", "R_0805", 10, 10)
    ops.move_component(board, "R1", 25, 25)
    assert board.components["R1"].position == Point(x=25, y=25)


def test_outline_contains():
    outline = BoardOutline(width=50, height=40)
    assert outline.contains(Point(x=25, y=20))
    assert not outline.contains(Point(x=60, y=20))


def test_diff_detects_changes():
    before = ops.create_board("demo", 50, 40)
    after = before.copy_deep()
    ops.add_component(after, "R1", "R_0805", 10, 10)
    ops.create_net(after, "GND")
    d = diff_boards(before, after)
    assert d.components_added == ["R1"]
    assert d.nets_added == ["GND"]
    assert not d.is_empty


def test_diff_empty_for_identical():
    b = ops.create_board("demo", 50, 40)
    assert diff_boards(b, b.copy_deep()).is_empty


def test_deep_copy_is_independent():
    board = ops.create_board("demo", 50, 40)
    ops.add_component(board, "R1", "R_0805", 10, 10)
    clone = board.copy_deep()
    ops.move_component(clone, "R1", 30, 30)
    assert board.components["R1"].position == Point(x=10, y=10)
    assert isinstance(clone, Board)

from coppermind.domain import operations as ops
from coppermind.domain.models import Layer
from coppermind.verification.checks import Severity, has_blocking, verify


def test_clean_board_has_no_blocking():
    board = ops.create_board("demo", 50, 40)
    ops.add_component(board, "R1", "R_0805", 10, 10)
    ops.create_net(board, "N1")
    ops.route_track(board, "N1", (10, 10), (20, 10), width=0.25)
    assert not has_blocking(verify(board))


def test_component_outside_outline_blocks():
    board = ops.create_board("demo", 50, 40)
    ops.add_component(board, "R1", "R_0805", 100, 100)
    v = verify(board)
    assert has_blocking(v)
    assert any(x.code == "COMPONENT_OUTSIDE_BOARD" for x in v)


def test_overlap_blocks():
    board = ops.create_board("demo", 50, 40)
    ops.add_component(board, "R1", "R_0805", 10, 10)
    ops.add_component(board, "R2", "R_0805", 10.2, 10)  # very close -> overlap
    v = verify(board)
    assert any(x.code == "COMPONENT_COLLISION" and x.severity == Severity.ERROR for x in v)


def test_track_unknown_net_blocks():
    board = ops.create_board("demo", 50, 40)
    ops.route_track(board, "GHOST", (1, 1), (2, 2))
    v = verify(board)
    assert any(x.code == "TRACK_UNKNOWN_NET" for x in v)


def test_thin_track_warns_with_citation():
    board = ops.create_board("demo", 50, 40)
    ops.create_net(board, "N1")
    ops.route_track(board, "N1", (1, 1), (2, 1), width=0.05)
    v = verify(board)
    thin = [x for x in v if x.code == "TRACK_TOO_THIN"]
    assert thin and thin[0].severity == Severity.WARNING
    assert "IPC-2221" in thin[0].rule  # explainable + cited
    assert not has_blocking(v)  # warning does not block


def test_non_copper_track_blocks():
    board = ops.create_board("demo", 50, 40)
    ops.create_net(board, "N1")
    ops.route_track(board, "N1", (1, 1), (2, 1), layer=Layer.F_SILKS)
    assert any(x.code == "TRACK_NON_COPPER_LAYER" for x in verify(board))

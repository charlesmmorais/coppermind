import pytest

from coppermind.domain import operations as ops
from coppermind.persistence import load_board, save_board


def _board():
    b = ops.create_board("Demo", 50, 40)
    ops.add_component(b, "R1", "R_0603", 10, 10, value="10k")
    ops.add_pad(b, "R1", "1", -0.8, 0, net="VCC")
    ops.create_net(b, "VCC")
    ops.route_track(b, "VCC", (0, 0), (5, 0))
    ops.add_via(b, 5, 0, net="VCC")
    return b


def test_save_load_roundtrip_is_lossless(tmp_path):
    b = _board()
    path = save_board(b, str(tmp_path / "demo.json"))
    loaded = load_board(path)
    assert loaded == b  # pydantic deep equality (ids included)


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_board(str(tmp_path / "nope.json"))


def test_save_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        save_board(_board(), str(tmp_path / "missing" / "demo.json"))

import pytest

from coppermind.safety import validate_input_file, validate_output_path


def test_validate_input_file_ok(tmp_path):
    f = tmp_path / "board.ses"
    f.write_text("(session)", encoding="utf-8")
    assert validate_input_file(str(f), {".ses"}) == str(f.resolve())


def test_validate_input_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_input_file(str(tmp_path / "nope.ses"), {".ses"})


def test_validate_input_file_wrong_suffix(tmp_path):
    f = tmp_path / "board.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_input_file(str(f), {".ses"})


def test_validate_input_file_rejects_directory(tmp_path):
    with pytest.raises(ValueError):
        validate_input_file(str(tmp_path), {".ses"})


def test_validate_output_path_ok(tmp_path):
    out = tmp_path / "out.ses"
    assert validate_output_path(str(out), {".ses"}) == str(out.resolve())


def test_validate_output_path_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_output_path(str(tmp_path / "missing" / "out.ses"), {".ses"})


def test_validate_output_path_wrong_suffix(tmp_path):
    with pytest.raises(ValueError):
        validate_output_path(str(tmp_path / "out.txt"), {".ses"})

from pathlib import Path

from coppermind.libraries import SymbolResolver


BASE = r'''(kicad_symbol_lib (version 20251024) (generator "kicad_symbol_editor")
  (generator_version "10.0")
  (symbol "R"
    (pin_names (offset 0))
    (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_1_1"
      (pin passive line (at 0 2.54 270) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -2.54 90) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))
    )
  )
)'''

CHILD = r'''(kicad_symbol_lib (version 20251024) (generator "kicad_symbol_editor")
  (generator_version "10.0")
  (symbol "R_Small"
    (extends "R")
    (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
  )
)'''


def test_resolves_kicad10_unpacked_symdir_and_parent(tmp_path: Path):
    symdir = tmp_path / "Device.kicad_symdir"
    symdir.mkdir()
    (symdir / "R.kicad_sym").write_text(BASE, encoding="utf-8")
    (symdir / "R_Small.kicad_sym").write_text(CHILD, encoding="utf-8")

    result = SymbolResolver(search_paths=[tmp_path]).resolve("Device:R_Small")

    assert result.source_path.endswith("R_Small.kicad_sym")
    assert result.extends == "Device:R"
    assert [pin.number for pin in result.pins] == ["1", "2"]
    assert [definition.lib_id for definition in result.definitions] == [
        "Device:R",
        "Device:R_Small",
    ]

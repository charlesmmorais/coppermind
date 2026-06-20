"""KiCAD 11 readiness: the codebase must be SWIG-free.

KiCAD 11 removes the legacy ``pcbnew`` SWIG bindings. Coppermind is IPC-first by
design; this guard fails CI if any source module imports pcbnew, guaranteeing we
never regress into the dependency the reference project was built on.
"""

import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "coppermind"


def test_no_pcbnew_swig_imports():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import pcbnew", "from pcbnew")):
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, f"SWIG pcbnew imports found (breaks KiCAD 11): {offenders}"


def test_ipc_is_the_only_kicad_binding_referenced():
    # The only KiCAD binding we depend on is kipy (IPC). Confirm it is referenced
    # and pcbnew is not, anywhere in the package.
    all_text = "\n".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))
    assert "kipy" in all_text
    assert "import pcbnew" not in all_text

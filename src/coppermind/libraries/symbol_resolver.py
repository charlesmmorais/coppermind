"""Resolve real KiCad symbols from packed or unpacked KiCad libraries.

Supported sources:

* installed/packed ``Library.kicad_sym`` files;
* KiCad 10+ source-style ``Library.kicad_symdir/`` directories;
* project ``sym-lib-table`` mappings.

No synthetic fallback exists by design. Missing libraries or symbols raise
``SymbolResolutionError``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from coppermind.circuit import ElectricalType, Pin


class SymbolResolutionError(LookupError):
    pass


class ResolvedSymbolDefinition(BaseModel):
    lib_id: str
    raw_s_expression: str


class ResolvedSymbol(BaseModel):
    lib_id: str
    library: str
    name: str
    source_path: str
    pins: list[Pin] = Field(default_factory=list)
    definitions: list[ResolvedSymbolDefinition] = Field(default_factory=list)
    extends: str | None = None

    def pins_by_number(self) -> dict[str, Pin]:
        return {pin.number: pin for pin in self.pins}


_TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()]+')
_UNIT_SUFFIX_RE = re.compile(r"_(\d+)_(\d+)$")
_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] == '"':
        body = token[1:-1]
        return body.replace(r'\"', '"').replace(r"\\", "\")
    return token


def _parse_sexpr(text: str) -> list[Any]:
    tokens = _TOKEN_RE.findall(text)
    stack: list[list[Any]] = []
    root: list[Any] | None = None
    for token in tokens:
        if token == "(":
            node: list[Any] = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            if root is None:
                root = node
        elif token == ")":
            if not stack:
                raise ValueError("unbalanced KiCad S-expression")
            stack.pop()
        else:
            if not stack:
                raise ValueError("token outside KiCad S-expression")
            stack[-1].append(_unquote(token))
    if stack or root is None:
        raise ValueError("unbalanced KiCad S-expression")
    return root


def _quoted_after(text: str, start: int) -> tuple[str, int]:
    i = text.find('"', start)
    if i < 0:
        raise ValueError("expected quoted symbol name")
    j = i + 1
    escaped = False
    out: list[str] = []
    while j < len(text):
        ch = text[j]
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            return "".join(out), j + 1
        else:
            out.append(ch)
        j += 1
    raise ValueError("unterminated quoted string")


def _matching_paren(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unterminated S-expression block")


def _top_level_symbols(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    depth = 0
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "(":
            if depth == 1 and text.startswith("(symbol", i):
                name, _ = _quoted_after(text, i + len("(symbol"))
                end = _matching_paren(text, i)
                found[name] = text[i:end]
                i = end
                continue
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return found


def _child(node: list[Any], key: str) -> list[Any] | None:
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == key:
            return item
    return None


def _collect_pins(node: list[Any], unit: int = 1) -> list[Pin]:
    pins: list[Pin] = []
    if node and node[0] == "symbol" and len(node) > 1 and isinstance(node[1], str):
        match = _UNIT_SUFFIX_RE.search(node[1])
        if match:
            unit = int(match.group(1))
    if node and node[0] == "pin" and len(node) >= 3:
        name_node = _child(node, "name")
        number_node = _child(node, "number")
        if number_node and len(number_node) > 1:
            pins.append(
                Pin(
                    number=str(number_node[1]),
                    name=str(name_node[1]) if name_node and len(name_node) > 1 else "",
                    electrical_type=ElectricalType.from_kicad(str(node[1])),
                    shape=str(node[2]),
                    unit=unit,
                )
            )
    for item in node:
        if isinstance(item, list):
            pins.extend(_collect_pins(item, unit))
    return pins


def _extends_name(node: list[Any]) -> str | None:
    ext = _child(node, "extends")
    if ext and len(ext) > 1:
        return str(ext[1])
    return None


def _normalize_definition(block: str, lib_id: str, library: str) -> str:
    name_start = block.find('"', len("(symbol"))
    _, after = _quoted_after(block, len("(symbol"))
    normalized = block[:name_start] + f'"{lib_id}"' + block[after:]

    def repl(match: re.Match[str]) -> str:
        parent = match.group(1)
        if ":" in parent:
            return match.group(0)
        return f'(extends "{library}:{parent}")'

    return re.sub(r'\(extends\s+"([^"]+)"\)', repl, normalized, count=1)


def _expand_env_path(value: str, project_dir: Path | None) -> Path:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "KIPRJMOD" and project_dir is not None:
            return str(project_dir)
        return os.environ.get(key, match.group(0))

    return Path(os.path.expanduser(_ENV_RE.sub(repl, value)))


def _default_search_paths() -> list[Path]:
    values: list[str] = []
    custom = os.environ.get("COPPERMIND_KICAD_SYMBOL_DIRS", "")
    if custom:
        values.extend(x for x in custom.split(os.pathsep) if x)
    for key in (
        "KICAD_SYMBOL_DIR",
        "KICAD12_SYMBOL_DIR",
        "KICAD11_SYMBOL_DIR",
        "KICAD10_SYMBOL_DIR",
        "KICAD9_SYMBOL_DIR",
        "KICAD8_SYMBOL_DIR",
    ):
        if os.environ.get(key):
            values.append(os.environ[key])

    if sys.platform.startswith("win"):
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        for version in ("12.0", "11.0", "10.0", "9.0", "8.0"):
            values.append(
                str(Path(program_files) / "KiCad" / version / "share" / "kicad" / "symbols")
            )
    elif sys.platform == "darwin":
        values.extend([
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/kicad/symbols",
        ])
    else:
        values.extend([
            "/usr/share/kicad/symbols",
            "/usr/local/share/kicad/symbols",
            "/usr/share/kicad-nightly/symbols",
        ])

    out: list[Path] = []
    seen: set[str] = set()
    for value in values:
        path = Path(os.path.expanduser(value))
        key = str(path)
        if key not in seen:
            out.append(path)
            seen.add(key)
    return out


def _table_libraries(path: Path, project_dir: Path | None) -> dict[str, Path]:
    if not path.is_file():
        return {}
    try:
        root = _parse_sexpr(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result: dict[str, Path] = {}
    for item in root[1:]:
        if not isinstance(item, list) or not item or item[0] != "lib":
            continue
        name = _child(item, "name")
        uri = _child(item, "uri")
        if name and len(name) > 1 and uri and len(uri) > 1:
            result[str(name[1])] = _expand_env_path(str(uri[1]), project_dir)
    return result


class SymbolResolver:
    """Resolve ``Library:Symbol`` against real KiCad library sources."""

    def __init__(
        self,
        search_paths: Iterable[str | Path] | None = None,
        project_dir: str | Path | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve() if project_dir else None
        self.search_paths = (
            [Path(p) for p in search_paths]
            if search_paths is not None
            else _default_search_paths()
        )
        self._cache: dict[str, ResolvedSymbol] = {}
        self._project_libraries = (
            _table_libraries(self.project_dir / "sym-lib-table", self.project_dir)
            if self.project_dir else {}
        )

    def _library_source(self, library: str) -> Path:
        mapped = self._project_libraries.get(library)
        if mapped and (mapped.is_file() or mapped.is_dir()):
            return mapped
        for directory in self.search_paths:
            packed = directory / f"{library}.kicad_sym"
            if packed.is_file():
                return packed
            unpacked = directory / f"{library}.kicad_symdir"
            if unpacked.is_dir():
                return unpacked
        searched = ", ".join(str(p) for p in self.search_paths) or "<none>"
        raise SymbolResolutionError(
            f"KiCad symbol library '{library}' was not found. Searched: {searched}. "
            "Set COPPERMIND_KICAD_SYMBOL_DIRS or pass SymbolResolver(search_paths=[...])."
        )

    @staticmethod
    def _symbol_source(source: Path, name: str) -> Path:
        if source.is_file():
            return source
        candidate = source / f"{name}.kicad_sym"
        if candidate.is_file():
            return candidate
        raise SymbolResolutionError(f"symbol file '{name}.kicad_sym' not found in {source}")

    def resolve(self, lib_id: str) -> ResolvedSymbol:
        if lib_id in self._cache:
            return self._cache[lib_id]
        if ":" not in lib_id:
            raise SymbolResolutionError(
                f"invalid KiCad symbol id '{lib_id}'; expected 'Library:Symbol'"
            )
        library, name = lib_id.split(":", 1)
        result = self._resolve(library, name, self._library_source(library), stack=[])
        self._cache[lib_id] = result
        return result

    def _resolve(
        self,
        library: str,
        name: str,
        source: Path,
        stack: list[str],
    ) -> ResolvedSymbol:
        lib_id = f"{library}:{name}"
        if lib_id in stack:
            raise SymbolResolutionError(
                f"cyclic symbol inheritance: {' -> '.join(stack + [lib_id])}"
            )

        symbol_path = self._symbol_source(source, name)
        text = symbol_path.read_text(encoding="utf-8")
        blocks = _top_level_symbols(text)
        block = blocks.get(name)
        if block is None:
            raise SymbolResolutionError(f"symbol '{lib_id}' not found in {symbol_path}")
        try:
            parsed = _parse_sexpr(block)
        except ValueError as exc:
            raise SymbolResolutionError(
                f"cannot parse '{lib_id}' from {symbol_path}: {exc}"
            ) from exc

        parent_name = _extends_name(parsed)
        pins = _collect_pins(parsed)
        definitions: list[ResolvedSymbolDefinition] = []
        if parent_name:
            parent = self._resolve(library, parent_name, source, stack + [lib_id])
            merged: dict[tuple[str, int], Pin] = {
                (p.number, p.unit): p for p in parent.pins
            }
            for pin in pins:
                merged[(pin.number, pin.unit)] = pin
            pins = list(merged.values())
            definitions.extend(parent.definitions)

        unique: dict[tuple[str, int], Pin] = {}
        for pin in pins:
            unique.setdefault((pin.number, pin.unit), pin)
        pins = list(unique.values())
        definitions.append(
            ResolvedSymbolDefinition(
                lib_id=lib_id,
                raw_s_expression=_normalize_definition(block, lib_id, library),
            )
        )
        return ResolvedSymbol(
            lib_id=lib_id,
            library=library,
            name=name,
            source_path=str(symbol_path),
            pins=pins,
            definitions=definitions,
            extends=f"{library}:{parent_name}" if parent_name else None,
        )

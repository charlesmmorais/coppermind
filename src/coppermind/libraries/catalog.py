"""Searchable catalog over the real KiCad symbol libraries.

The catalog is intentionally metadata-only: it discovers candidate
``Library:Symbol`` ids without manufacturing symbols. Exact symbol details are
still resolved through :class:`SymbolResolver` before they enter the Circuit IR.
"""

from __future__ import annotations

from pathlib import Path

from coppermind.libraries.symbol_resolver import SymbolResolver


def _top_level_symbol_names(text: str) -> list[str]:
    """Return only top-level ``(symbol ...)`` names from a KiCad library file."""
    names: list[str] = []
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
                q1 = text.find('"', i + len("(symbol"))
                if q1 >= 0:
                    q2 = q1 + 1
                    escaped_name = False
                    while q2 < len(text):
                        c2 = text[q2]
                        if escaped_name:
                            escaped_name = False
                        elif c2 == "\\":
                            escaped_name = True
                        elif c2 == '"':
                            names.append(text[q1 + 1:q2])
                            break
                        q2 += 1
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return names


def _library_sources(resolver: SymbolResolver) -> dict[str, Path]:
    """Collect project mappings plus installed packed/unpacked libraries."""
    result: dict[str, Path] = {}
    project_libraries = getattr(resolver, "_project_libraries", {})
    for name, path in project_libraries.items():
        candidate = Path(path)
        if candidate.exists():
            result[name] = candidate

    for directory in resolver.search_paths:
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in root.glob("*.kicad_sym"):
            result.setdefault(path.stem, path)
        for path in root.glob("*.kicad_symdir"):
            result.setdefault(path.name.removesuffix(".kicad_symdir"), path)
    return result


def _symbols_in_source(source: Path) -> list[str]:
    if source.is_dir():
        return sorted(path.stem for path in source.glob("*.kicad_sym"))
    try:
        return sorted(_top_level_symbol_names(source.read_text(encoding="utf-8")))
    except OSError:
        return []


def find_symbols(
    resolver: SymbolResolver,
    query: str,
    library: str | None = None,
    limit: int = 20,
) -> list[dict[str, object]]:
    """Find real KiCad symbols by library/name substring, ranked deterministically."""
    q = query.strip().lower()
    if not q:
        raise ValueError("query must not be empty")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    sources = _library_sources(resolver)
    if library:
        source = sources.get(library)
        if source is None:
            # Preserve SymbolResolver's detailed not-found diagnostics.
            source = resolver._library_source(library)
        sources = {library: source}

    ranked: list[tuple[int, str, str, Path]] = []
    for lib_name, source in sorted(sources.items()):
        for symbol_name in _symbols_in_source(source):
            lib_id = f"{lib_name}:{symbol_name}"
            name_l = symbol_name.lower()
            lib_l = lib_name.lower()
            id_l = lib_id.lower()
            if q not in id_l:
                continue
            if name_l == q:
                score = 0
            elif name_l.startswith(q):
                score = 1
            elif q in name_l:
                score = 2
            elif lib_l == q:
                score = 3
            else:
                score = 4
            ranked.append((score, lib_id.lower(), lib_id, source))

    ranked.sort(key=lambda item: (item[0], item[1]))
    result: list[dict[str, object]] = []
    for _, _, lib_id, source in ranked[:limit]:
        resolved = resolver.resolve(lib_id)
        result.append({
            "lib_id": lib_id,
            "library": resolved.library,
            "name": resolved.name,
            "pin_count": len(resolved.pins),
            "extends": resolved.extends,
            "source_path": str(source),
        })
    return result

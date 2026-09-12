"""Compatibility helpers backed by the real KiCad symbol resolver.

The previous implementation manufactured rectangles and silently treated every
unknown symbol as a two-pin device. That behaviour was unsafe for engineering
work and has been removed. Missing symbols now fail explicitly.
"""

from __future__ import annotations

from coppermind.libraries import SymbolResolver


def pin_numbers(lib_id: str, resolver: SymbolResolver | None = None) -> list[str]:
    resolved = (resolver or SymbolResolver()).resolve(lib_id)
    return list(dict.fromkeys(pin.number for pin in resolved.pins))


def lib_symbol_def(lib_id: str, resolver: SymbolResolver | None = None) -> str:
    resolved = (resolver or SymbolResolver()).resolve(lib_id)
    return resolved.definitions[-1].raw_s_expression

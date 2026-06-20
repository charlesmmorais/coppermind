"""Minimal S-expression parser for Specctra DSN/SES files.

Specctra files are LISP-like S-expressions. This tiny tokenizer/parser returns
nested Python lists (atoms as str/float), enough to walk a routed session.
Pure and dependency-free.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r'\(|\)|"[^"]*"|[^\s()]+')

SExpr = list  # nested list of str | float | list


def parse(text: str) -> list:
    """Parse S-expression text into nested lists. Returns the top-level node."""
    tokens = _TOKEN.findall(text)
    pos = 0

    def atom(tok: str):  # noqa: ANN202
        if tok.startswith('"') and tok.endswith('"'):
            return tok[1:-1]
        try:
            return float(tok) if ("." in tok or "e" in tok.lower()) else int(tok)
        except ValueError:
            return tok

    def walk() -> list:
        nonlocal pos
        node: list = []
        while pos < len(tokens):
            tok = tokens[pos]
            pos += 1
            if tok == "(":
                node.append(walk())
            elif tok == ")":
                return node
            else:
                node.append(atom(tok))
        return node

    tree = walk()
    # The top level is a wrapper list; return the first real node.
    return tree[0] if len(tree) == 1 and isinstance(tree[0], list) else tree


def head(node: list) -> str | None:
    """First element (the tag) of an S-expression node, if it's a symbol."""
    return node[0] if node and isinstance(node[0], str) else None


def find(node: list, tag: str) -> list | None:
    """First direct child sub-list whose head == tag."""
    for child in node:
        if isinstance(child, list) and head(child) == tag:
            return child
    return None


def find_all(node: list, tag: str) -> list[list]:
    """All direct child sub-lists whose head == tag."""
    return [c for c in node if isinstance(c, list) and head(c) == tag]

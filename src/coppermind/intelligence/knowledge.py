"""The EE knowledge base — data-driven, versioned, and citable.

Rules live in ``ee_rules.yaml`` (next to this module), so contributors can add or
edit design knowledge without touching Python. Each rule has a stable id, a
title, a category, a one-line statement, a citation (standard or well-known
practice), and a rationale. The critique engine references rule ids so each
finding points back to *why* — auditable, and it teaches the user.

Override the rules file with the ``COPPERMIND_RULES`` environment variable.
A governance test enforces that every rule is complete and ids are unique.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

_DEFAULT_RULES_PATH = Path(__file__).with_name("ee_rules.yaml")


class Rule(BaseModel):
    id: str
    title: str
    category: str
    statement: str
    citation: str
    rationale: str


def _rules_path() -> Path:
    return Path(os.environ["COPPERMIND_RULES"]) if "COPPERMIND_RULES" in os.environ else _DEFAULT_RULES_PATH


@lru_cache(maxsize=None)
def _load() -> tuple[str, dict[str, Rule]]:
    data = yaml.safe_load(_rules_path().read_text(encoding="utf-8")) or {}
    version = str(data.get("version", "0"))
    rules = {r["id"]: Rule(**r) for r in data.get("rules", [])}
    return version, rules


def reload_rules() -> None:
    """Drop the cached rules (call after editing the YAML at runtime)."""
    _load.cache_clear()


def _version() -> str:
    return _load()[0]


# Module-level constant kept for back-compat; reflects the loaded KB version.
KNOWLEDGE_BASE_VERSION: str = _version()


def all_rules() -> list[Rule]:
    return list(_load()[1].values())


def get_rule(rule_id: str) -> Rule:
    rules = _load()[1]
    if rule_id not in rules:
        raise KeyError(f"unknown rule '{rule_id}'")
    return rules[rule_id]

"""The EE knowledge base — explicit, versioned, and citable.

The reference project hid any "best practice" knowledge inside opaque prompts.
Coppermind makes it data: every rule has a stable id, a one-line statement, a
citation (standard or well-known practice), and a rationale. The critique engine
references these rules so each finding can point back to *why* — auditable, and
it teaches the user instead of just flagging.

Bump KNOWLEDGE_BASE_VERSION when rules change; a governance test enforces that
every rule is complete and ids are unique.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

KNOWLEDGE_BASE_VERSION = "2026.06"


class RuleCategory(str, Enum):
    POWER = "power"
    DECOUPLING = "decoupling"
    GROUNDING = "grounding"
    MANUFACTURABILITY = "manufacturability"


class Rule(BaseModel):
    id: str
    title: str
    category: RuleCategory
    statement: str
    citation: str
    rationale: str


_RULES: dict[str, Rule] = {
    r.id: r
    for r in [
        Rule(
            id="EE.POWER.TRACE_WIDTH",
            title="Power trace width for current",
            category=RuleCategory.POWER,
            statement="Size power/ground traces for their current using IPC-2221.",
            citation="IPC-2221",
            rationale="Undersized copper overheats; width must match current, "
            "copper weight and allowed temperature rise.",
        ),
        Rule(
            id="EE.DECOUPLING.PER_IC",
            title="Decoupling capacitor per IC",
            category=RuleCategory.DECOUPLING,
            statement="Place a decoupling capacitor (~100 nF) close to each IC power pin.",
            citation="Common practice (e.g. Horowitz & Hill, IC datasheets)",
            rationale="Local charge reservoir suppresses supply noise and keeps "
            "the high-frequency return loop small.",
        ),
        Rule(
            id="EE.GROUNDING.GND_PRESENT",
            title="Ground net present",
            category=RuleCategory.GROUNDING,
            statement="A design with power nets should define a ground (GND) net.",
            citation="Common practice",
            rationale="Every supply needs a defined return path; a missing GND "
            "usually means an incomplete power scheme.",
        ),
    ]
}


def all_rules() -> list[Rule]:
    return list(_RULES.values())


def get_rule(rule_id: str) -> Rule:
    if rule_id not in _RULES:
        raise KeyError(f"unknown rule '{rule_id}'")
    return _RULES[rule_id]

"""Design intelligence: citable EE knowledge, proactive critique, design blocks.

KiCAD-independent by design — all of this runs and is tested without KiCAD.
"""

from coppermind.intelligence.blocks import BLOCKS, BlockResult
from coppermind.intelligence.critique import critique, is_power_net
from coppermind.intelligence.knowledge import (
    KNOWLEDGE_BASE_VERSION,
    Rule,
    all_rules,
    get_rule,
)
from coppermind.intelligence.trace_width import min_trace_width_mm

__all__ = [
    "BLOCKS",
    "BlockResult",
    "KNOWLEDGE_BASE_VERSION",
    "Rule",
    "all_rules",
    "critique",
    "get_rule",
    "is_power_net",
    "min_trace_width_mm",
]

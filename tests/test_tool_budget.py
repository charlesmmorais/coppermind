"""Context economy as a tested invariant, not a slogan.

The reference project advertised a "70% context reduction" router that was never
actually active. Here we make the claim falsifiable: the always-visible set
(core + discovery) must stay small and cheap, and the routed long tail must NOT
be always-visible — it is reachable only via progressive discovery.
"""

import inspect

from coppermind.tools import CORE_TOOLS, DISCOVERY_TOOLS, REGISTRY

MAX_VISIBLE_TOOLS = 14
MAX_APPROX_TOKENS = 2200


def _approx_tokens(text: str) -> int:
    return len(text) // 4


def _visible():
    return CORE_TOOLS + DISCOVERY_TOOLS


def test_visible_tool_count_within_budget():
    n = len(_visible())
    assert n <= MAX_VISIBLE_TOOLS, (
        f"{n} always-visible tools exceeds budget {MAX_VISIBLE_TOOLS}; "
        "move low-frequency tools into the routed registry."
    )


def test_routed_tools_are_not_visible():
    visible = {fn.__name__ for fn in _visible()}
    routed = set(REGISTRY.names)
    assert visible.isdisjoint(routed)
    assert len(routed) >= 5  # a real long tail exists behind discovery


def test_visible_schema_text_within_budget():
    blob = []
    for fn in _visible():
        blob.append(fn.__name__)
        blob.append((fn.__doc__ or "").strip())
        blob.append(str(inspect.signature(fn)))
    total = _approx_tokens("\n".join(blob))
    assert total <= MAX_APPROX_TOKENS, f"visible tool defs ~{total} tokens > {MAX_APPROX_TOKENS}"


def test_every_visible_tool_is_documented():
    for fn in _visible():
        assert (fn.__doc__ or "").strip(), f"{fn.__name__} is missing a docstring"


def test_tool_names_follow_resource_action_convention():
    allowed = ("project_", "component_", "net_", "board_", "design_",
               "list_", "get_", "search_", "execute_")
    for fn in _visible():
        assert fn.__name__.startswith(allowed), f"{fn.__name__} breaks naming convention"

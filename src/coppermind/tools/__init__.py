"""Tools layer.

* CORE_TOOLS      — always-visible, high-frequency operations.
* DISCOVERY_TOOLS — always-visible gateway to the routed long tail.
* REGISTRY        — routed (on-demand) tools, found via discovery.

Keeping tool logic free of the MCP SDK means it is unit-testable without a
server, and the server stays a thin registration layer.
"""

from coppermind.tools.core import CORE_TOOLS
from coppermind.tools.discovery import DISCOVERY_TOOLS
from coppermind.tools.registry import REGISTRY

__all__ = ["CORE_TOOLS", "DISCOVERY_TOOLS", "REGISTRY"]

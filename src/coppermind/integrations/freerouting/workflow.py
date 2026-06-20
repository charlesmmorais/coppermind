"""End-to-end Freerouting autoroute workflow (DSN -> route -> SES -> board).

Ties the pieces together: run Freerouting (local Java or Docker/Podman) on a
Specctra .dsn, parse the resulting .ses, and apply the routed tracks/vias to a
Coppermind board. The board mutation is pure and tested; only the engine call is
external (gated).

DSN acquisition note: kicad-cli does not export Specctra DSN, so the .dsn comes
from KiCAD's File > Export > Specctra DSN (or an IPC action). Coppermind
orchestrates routing + import from there.
"""

from __future__ import annotations

import logging

from coppermind.domain.models import Board
from coppermind.integrations.autorouter import AutoRouter, FreeroutingRunner
from coppermind.integrations.freerouting.ses import RouteResult, parse_ses

logger = logging.getLogger(__name__)


def apply_route_to_board(
    board: Board, result: RouteResult, replace_routing: bool = True
) -> Board:
    """Return a new board with the routed tracks/vias applied.

    With ``replace_routing`` (default), existing copper routing is cleared first
    — the autorouter's output is authoritative for the routed nets.
    """
    out = board.copy_deep()
    if replace_routing:
        out.tracks = []
        out.vias = []
    out.tracks.extend(t.model_copy(deep=True) for t in result.tracks)
    out.vias.extend(v.model_copy(deep=True) for v in result.vias)
    return out


def autoroute_dsn(
    dsn_path: str,
    ses_path: str,
    jar_path: str,
    max_passes: int = 10,
    router: AutoRouter | None = None,
) -> RouteResult:
    """Route a .dsn into a .ses with Freerouting and parse the result.

    The subprocess call is delegated to the AutoRouter (default: FreeroutingRunner,
    which auto-selects Java or Docker/Podman). Returns the parsed RouteResult.
    """
    router = router or FreeroutingRunner(jar_path, max_passes=max_passes)
    if not router.is_available():
        raise RuntimeError(
            "Freerouting is not available: install Java 21+ or Docker/Podman and "
            "place the freerouting jar (see route_check)."
        )
    produced = router.route(dsn_path, ses_path, max_passes)  # pragma: no cover - external
    with open(produced, encoding="utf-8") as fh:  # pragma: no cover - external
        return parse_ses(fh.read())

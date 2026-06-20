from coppermind.backends.memory_backend import MemoryBackend
from coppermind.session import Session
from coppermind.tools import REGISTRY
from coppermind.tools.core import net_route, project_create

SES = '(session "b.ses" (routes (resolution um 10) (network_out (net "GND" ' \
      '(wire (path F.Cu 2500 0 0 100000 0)) (via "V" 100000 0)))))'


def _session():
    s = Session(backend=MemoryBackend())
    project_create(s, "P", 50, 40)
    return s


def test_autorouting_tools_discoverable():
    names = set(REGISTRY.names)
    assert {"route_import_ses", "route_autoroute", "route_export_dsn", "route_check"} <= names
    assert "routing" in REGISTRY.list_categories()


def test_route_import_ses_replaces(tmp_path):
    s = _session()
    net_route(s, "OLD", 0, 0, 1, 1)  # stale routing on working board
    ses = tmp_path / "r.ses"
    ses.write_text(SES, encoding="utf-8")
    out = REGISTRY.execute_tool(s, "route_import_ses", {"ses_path": str(ses)})
    assert out["tracks"] == 1 and out["vias"] == 1
    board = s.document.working()
    assert len(board.tracks) == 1 and board.tracks[0].net == "GND"


def test_route_export_dsn_guides_when_unsupported():
    s = _session()  # memory backend has no DSN export
    out = REGISTRY.execute_tool(s, "route_export_dsn", {"dsn_path": "/tmp/b.dsn"})
    assert out["ok"] is False and "Specctra" in out["hint"]

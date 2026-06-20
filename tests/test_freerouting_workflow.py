from coppermind.domain import operations as ops
from coppermind.integrations.autorouter import AutoRouter
from coppermind.integrations.freerouting import apply_route_to_board, autoroute_dsn, parse_ses

SES = '(session "b.ses" (routes (resolution um 10) (network_out (net "GND" ' \
      '(wire (path F.Cu 2500 0 0 100000 0)) (via "V" 100000 0)))))'


def test_apply_route_replaces_stale_routing():
    b = ops.create_board("b", 50, 40)
    ops.create_net(b, "GND")
    ops.route_track(b, "GND", (0, 0), (1, 1))  # stale
    result = parse_ses(SES)
    out = apply_route_to_board(b, result, replace_routing=True)
    assert len(out.tracks) == 1 and len(out.vias) == 1
    assert out.tracks[0].end.x == 10.0          # the routed one
    assert len(b.tracks) == 1                    # base untouched


def test_apply_route_can_append():
    b = ops.create_board("b", 50, 40)
    ops.route_track(b, "X", (0, 0), (1, 1))
    out = apply_route_to_board(b, parse_ses(SES), replace_routing=False)
    assert len(out.tracks) == 2


class _FakeRouter(AutoRouter):
    name = "fake"

    def __init__(self, ses_text):
        self._ses = ses_text

    def is_available(self):
        return True

    def route(self, dsn_path, ses_path, max_passes=10):
        with open(ses_path, "w", encoding="utf-8") as fh:
            fh.write(self._ses)
        return ses_path


def test_autoroute_dsn_with_fake_router(tmp_path):
    ses = tmp_path / "out.ses"
    result = autoroute_dsn(str(tmp_path / "in.dsn"), str(ses), "/unused.jar",
                           router=_FakeRouter(SES))
    assert len(result.tracks) == 1 and len(result.vias) == 1


def test_autoroute_unavailable_raises(tmp_path):
    class Down(AutoRouter):
        name = "down"
        def is_available(self): return False
        def route(self, *a, **k): raise AssertionError("should not run")
    import pytest
    with pytest.raises(RuntimeError):
        autoroute_dsn("a.dsn", "b.ses", "/j.jar", router=Down())

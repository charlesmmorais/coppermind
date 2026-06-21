"""A stuck autorouter must not hang the session: timeouts surface as RuntimeError."""

import subprocess

import pytest

from coppermind.integrations.autorouter import AutoRouter, FreeroutingRunner
from coppermind.integrations.freerouting import autoroute_dsn


def test_runner_stores_timeout():
    r = FreeroutingRunner("/x.jar", max_passes=5, timeout_s=42)
    assert r.timeout_s == 42


class _HangingRouter(AutoRouter):
    name = "hang"

    def is_available(self) -> bool:
        return True

    def route(self, dsn_path, ses_path, max_passes=10):
        raise subprocess.TimeoutExpired(cmd="freerouting", timeout=1)


def test_timeout_becomes_runtimeerror(tmp_path):
    with pytest.raises(RuntimeError, match="timed out"):
        autoroute_dsn(
            str(tmp_path / "b.dsn"), str(tmp_path / "b.ses"), "/x.jar",
            timeout_s=1, router=_HangingRouter(),
        )

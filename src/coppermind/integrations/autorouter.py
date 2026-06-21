"""Autorouter integration (Freerouting) behind a swappable interface.

The DSN→route→SES workflow runs an external engine. We keep the *decisions*
pure and tested — which runtime to use (local Java vs Docker/Podman) and the
exact command line — while the subprocess call is isolated and network/OS-gated.
Swapping in another autorouter is just another AutoRouter implementation.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


class AutoRouter(ABC):
    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def route(self, dsn_path: str, ses_path: str, max_passes: int = 10) -> str:
        """Route a Specctra DSN, write SES, return the SES path."""


@dataclass(frozen=True)
class FreeroutingRuntime:
    kind: str          # "java" | "docker" | "podman" | "none"
    detail: str = ""


def resolve_runtime(which: Callable[[str], str | None] = shutil.which) -> FreeroutingRuntime:
    """Pick a runtime: local Java first, then Docker, then Podman."""
    if which("java"):
        return FreeroutingRuntime("java", "local java")
    if which("docker"):
        return FreeroutingRuntime("docker", "docker fallback")
    if which("podman"):
        return FreeroutingRuntime("podman", "podman fallback")
    return FreeroutingRuntime("none", "no java/docker/podman found")


def build_freerouting_command(
    runtime: FreeroutingRuntime,
    jar_path: str,
    dsn_path: str,
    ses_path: str,
    max_passes: int = 10,
    image: str = "eclipse-temurin:21-jre",
) -> list[str]:
    """Build the argv to run Freerouting under the chosen runtime. Pure."""
    fr_args = ["-de", dsn_path, "-do", ses_path, "-mp", str(max_passes)]
    if runtime.kind == "java":
        return ["java", "-jar", jar_path, *fr_args]
    if runtime.kind in ("docker", "podman"):
        return [
            runtime.kind, "run", "--rm",
            "-v", f"{jar_path}:/fr.jar",
            "-v", f"{dsn_path}:{dsn_path}",
            "-v", f"{ses_path}:{ses_path}",
            image, "java", "-jar", "/fr.jar", *fr_args,
        ]
    raise RuntimeError("no Freerouting runtime available (install Java 21+ or Docker/Podman)")


class FreeroutingRunner(AutoRouter):
    name = "freerouting"

    def __init__(self, jar_path: str, max_passes: int = 10, timeout_s: int = 600) -> None:
        self.jar_path = jar_path
        self.max_passes = max_passes
        self.timeout_s = timeout_s

    def runtime(self) -> FreeroutingRuntime:
        return resolve_runtime()

    def is_available(self) -> bool:
        import os

        return self.runtime().kind != "none" and os.path.exists(self.jar_path)

    def check(self) -> dict:
        import os

        rt = self.runtime()
        return {
            "runtime": rt.kind,
            "detail": rt.detail,
            "jar_present": os.path.exists(self.jar_path),
            "ready": self.is_available(),
        }

    def route(self, dsn_path: str, ses_path: str, max_passes: int | None = None) -> str:  # pragma: no cover - external
        import subprocess

        cmd = build_freerouting_command(
            self.runtime(), self.jar_path, dsn_path, ses_path, max_passes or self.max_passes
        )
        # A bounded timeout prevents a stuck autorouter from hanging the session.
        subprocess.run(cmd, check=True, capture_output=True, timeout=self.timeout_s)
        return ses_path

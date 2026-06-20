import pytest

from coppermind.integrations.autorouter import (
    FreeroutingRuntime,
    build_freerouting_command,
    resolve_runtime,
)


def test_resolve_prefers_java_then_docker_then_podman():
    assert resolve_runtime(lambda n: "/usr/bin/java" if n == "java" else None).kind == "java"
    assert resolve_runtime(lambda n: "/usr/bin/docker" if n == "docker" else None).kind == "docker"
    assert resolve_runtime(lambda n: "/usr/bin/podman" if n == "podman" else None).kind == "podman"
    assert resolve_runtime(lambda n: None).kind == "none"


def test_build_java_command():
    cmd = build_freerouting_command(FreeroutingRuntime("java"), "/fr.jar", "/b.dsn", "/b.ses", 12)
    assert cmd[:3] == ["java", "-jar", "/fr.jar"]
    assert "-mp" in cmd and "12" in cmd
    assert "/b.dsn" in cmd and "/b.ses" in cmd


def test_build_docker_command_mounts_files():
    cmd = build_freerouting_command(FreeroutingRuntime("docker"), "/fr.jar", "/b.dsn", "/b.ses")
    assert cmd[0] == "docker" and "run" in cmd
    assert any("/b.dsn:/b.dsn" in part for part in cmd)


def test_no_runtime_raises():
    with pytest.raises(RuntimeError):
        build_freerouting_command(FreeroutingRuntime("none"), "/fr.jar", "/b.dsn", "/b.ses")

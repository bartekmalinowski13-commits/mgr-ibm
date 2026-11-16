"""The parse sandbox: same result as in-process, limits become ParseErrors, no secrets leak."""

from __future__ import annotations

import signal
import sys

import pytest

from bomagent_cad import FileRef, ParseError, parse_files
from bomagent_cad.sandbox import (
    MiB,
    SandboxLimits,
    child_env,
    killed_error,
    parse_files_sandboxed,
)
from bomagent_testing.data import KICAD_FIXTURES, kicad_project_paths

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="resource limits are enforced on Linux"
)


def _files() -> list[FileRef]:
    return [FileRef.from_path(p) for p in kicad_project_paths("pulse-ox")]


def test_sandbox_result_equals_in_process_result():
    files = _files()
    assert parse_files_sandboxed(files).model_dump() == parse_files(files).model_dump()


def test_tiny_memory_limit_is_a_resource_error():
    with pytest.raises(ParseError) as err:
        parse_files_sandboxed(_files(), SandboxLimits(memory_bytes=8 * MiB))
    assert err.value.code == "parse.resource_limit"


def test_wall_clock_timeout_is_a_timeout_error():
    with pytest.raises(ParseError) as err:
        parse_files_sandboxed(_files(), SandboxLimits(timeout_seconds=0.01))
    assert err.value.code == "parse.timeout"


def test_parse_errors_keep_their_code_through_the_sandbox():
    with pytest.raises(ParseError) as err:
        parse_files_sandboxed([FileRef("x.brd", b"binary")])
    assert err.value.code == "unsupported.allegro_brd"


def test_cpu_signal_and_oom_map_to_resource_limit():
    assert killed_error(-int(signal.SIGXCPU), b"").code == "parse.resource_limit"
    assert killed_error(-int(signal.SIGKILL), b"").code == "parse.resource_limit"
    assert "memory" in str(killed_error(1, b"MemoryError")).lower()


def test_child_env_drops_secrets():
    parent = {
        "BOMAGENT_DATABASE_URL": "postgresql://u:p@h/db",
        "BOMAGENT_MIGRATOR_DATABASE_URL": "postgresql://u:p@h/db",
        "AWS_SECRET_ACCESS_KEY": "s",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/creds",
        "ANTHROPIC_API_KEY": "k",
        "LANG": "C.UTF-8",
    }
    env = child_env(parent)
    assert env.get("LANG") == "C.UTF-8"
    assert not [k for k in env if "DATABASE" in k or k.startswith(("AWS_", "ANTHROPIC"))]


def test_limits_from_env():
    limits = SandboxLimits.from_env(
        {
            "BOMAGENT_PARSE_MEMORY_MB": "256",
            "BOMAGENT_PARSE_CPU_SECONDS": "5",
            "BOMAGENT_PARSE_TIMEOUT_SECONDS": "7.5",
        }
    )
    assert (limits.memory_bytes, limits.cpu_seconds, limits.timeout_seconds) == (256 * MiB, 5, 7.5)
    assert SandboxLimits.from_env({}) == SandboxLimits()


def test_inprocess_mode(monkeypatch):
    monkeypatch.setenv("BOMAGENT_PARSE_SANDBOX", "inprocess")
    assert parse_files_sandboxed(_files()).components
    assert KICAD_FIXTURES.exists()


def test_project_size_is_bounded_before_files_are_loaded():
    from bomagent_cad.sandbox import ProjectSize

    budget = ProjectSize(max_files=2, max_bytes=10)
    budget.add("a", 4)
    budget.add("b", 6)
    with pytest.raises(ParseError) as too_many:
        budget.add("c", 0)
    assert too_many.value.code == "project.too_large"
    with pytest.raises(ParseError) as too_big:
        ProjectSize(max_files=5, max_bytes=10).add("x", 11)
    assert too_big.value.code == "project.too_large"


@pytest.mark.skipif(sys.platform != "linux", reason="prctl is Linux only")
def test_the_parent_is_not_dumpable_so_the_child_cannot_read_its_proc_entries():
    import ctypes

    from bomagent_cad.sandbox import harden_parent

    harden_parent()
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(3, 0, 0, 0, 0) == 0  # PR_GET_DUMPABLE


# ---------------------------------------------------------------- child hardening (SEC-01)

_PROBE = r"""
import ctypes, json, resource, socket, sys
from bomagent_cad._sandbox_child import apply_hardening

report = apply_hardening()
libc = ctypes.CDLL(None, use_errno=True)
out = {
    "report": report,
    "no_new_privs": libc.prctl(39, 0, 0, 0, 0),  # PR_GET_NO_NEW_PRIVS
    "nofile": resource.getrlimit(resource.RLIMIT_NOFILE)[0],
    "fsize": resource.getrlimit(resource.RLIMIT_FSIZE)[0],
    "core": resource.getrlimit(resource.RLIMIT_CORE)[0],
}
port, probe_path = int(sys.argv[1]), sys.argv[2]
try:
    socket.create_connection(("127.0.0.1", port), timeout=2).close()
    out["connected"] = True
except OSError:
    out["connected"] = False
try:
    with open(probe_path, "wb") as f:
        f.write(b"x" * 10)
        f.flush()
    out["wrote"] = True
except OSError:
    out["wrote"] = False

print(json.dumps(out))
"""


def _probe(tmp_path) -> dict:
    import json
    import socket
    import subprocess

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        proc = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                _PROBE,
                str(listener.getsockname()[1]),
                str(tmp_path / "probe.bin"),
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    return json.loads(proc.stdout.splitlines()[-1])


def test_child_cannot_gain_privileges_and_has_small_file_limits(tmp_path):
    out = _probe(tmp_path)
    assert out["no_new_privs"] == 1
    assert out["report"]["no_new_privs"] is True
    assert out["nofile"] <= 64
    assert out["fsize"] == 0  # writes to regular files fail
    assert out["core"] == 0
    assert out["wrote"] is False


def test_child_loses_the_network_when_the_kernel_allows_a_new_namespace(tmp_path):
    out = _probe(tmp_path)
    if not out["report"]["network_isolated"]:
        pytest.skip("this environment forbids unshare(CLONE_NEWNET); the limit is best effort")
    assert out["connected"] is False


def test_hardening_failures_are_reported_not_raised(monkeypatch):
    from bomagent_cad import _sandbox_child

    limits: list[str] = []
    # never apply the real limits to the test runner itself
    monkeypatch.setattr(_sandbox_child, "_limit", lambda kind, value: limits.append(kind))
    monkeypatch.setattr(_sandbox_child, "_prctl", lambda *a: -1)
    monkeypatch.setattr(_sandbox_child, "_unshare_network", lambda: False)
    report = _sandbox_child.apply_hardening()
    assert report["no_new_privs"] is False
    assert report["network_isolated"] is False
    assert {"RLIMIT_CORE", "RLIMIT_NOFILE", "RLIMIT_FSIZE"} <= set(limits)


def test_parent_reports_what_the_child_could_apply(caplog, monkeypatch):
    import logging

    from bomagent_cad import sandbox

    monkeypatch.setattr(sandbox, "_reported", set())
    with caplog.at_level(logging.INFO, logger="bomagent_cad.sandbox"):
        sandbox._report_hardening({"hardening": {"no_new_privs": True, "network_isolated": False}})
        sandbox._report_hardening({"hardening": {"no_new_privs": True, "network_isolated": False}})
        sandbox._report_hardening({"hardening": {"no_new_privs": True, "network_isolated": True}})
        sandbox._report_hardening({"no": "hardening"})
    messages = [r.getMessage() for r in caplog.records]
    assert sum("not fully isolated" in m for m in messages) == 1  # once per outcome
    assert sum("empty network namespace" in m for m in messages) == 1


def test_real_fixtures_parse_in_the_hardened_child_and_errors_keep_their_code():
    """NOFILE 32 / FSIZE 0 must not break real parsers (pipes only, no temp files)."""
    assert parse_files_sandboxed(_files()).components
    with pytest.raises(ParseError) as err:
        parse_files_sandboxed([FileRef("x.unknown-extension", b"not a design")])
    assert err.value.code.startswith("parse.") or "." in err.value.code


def test_hardening_exceptions_are_reported_not_raised(monkeypatch):
    from bomagent_cad import _sandbox_child

    monkeypatch.setattr(_sandbox_child, "_limit", lambda kind, value: None)

    def boom(*args):
        raise OSError("no libc")

    monkeypatch.setattr(_sandbox_child, "_prctl", boom)
    monkeypatch.setattr(_sandbox_child, "_unshare_network", boom)
    assert _sandbox_child.apply_hardening() == {"no_new_privs": False, "network_isolated": False}

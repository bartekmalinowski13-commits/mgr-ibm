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

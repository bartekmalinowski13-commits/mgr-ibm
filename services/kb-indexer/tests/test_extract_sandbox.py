"""KB documents are extracted in the resource-limited parse sandbox (ingest review I4)."""

from __future__ import annotations

import pytest

from bomagent_cad.sandbox import SandboxLimits
from bomagent_kb import ExtractionError, extract
from bomagent_kb_indexer.sandbox import extract_sandboxed, limits_from_env
from bomagent_testing.pdf import make_nested_pdf, make_pdf

MiB = 1024 * 1024


def test_sandboxed_result_equals_in_process_result():
    data = make_pdf(["Ordering information SANDBOX-1 regulator", "page two"])
    assert extract_sandboxed("a.pdf", data) == extract("a.pdf", data)
    text = b"notes\fsecond page"
    assert extract_sandboxed("n.txt", text) == extract("n.txt", text)


def test_hostile_pdf_in_the_child_is_an_extraction_error():
    with pytest.raises(ExtractionError, match="unreadable PDF"):
        extract_sandboxed("nested.pdf", make_nested_pdf())


def test_unsupported_type_keeps_its_message_through_the_child():
    with pytest.raises(ExtractionError, match="unsupported knowledge-base file type"):
        extract_sandboxed("x.exe", b"MZ")


def test_memory_limit_is_an_extraction_error():
    tiny = SandboxLimits(memory_bytes=32 * MiB, cpu_seconds=10, timeout_seconds=30)
    with pytest.raises(ExtractionError, match=r"resource limit|memory"):
        extract_sandboxed("a.pdf", make_pdf(["x"]), limits=tiny)


def test_wall_clock_timeout_is_an_extraction_error():
    instant = SandboxLimits(memory_bytes=1024 * MiB, cpu_seconds=10, timeout_seconds=0.001)
    with pytest.raises(ExtractionError, match="longer than"):
        extract_sandboxed("a.pdf", make_pdf(["x"]), limits=instant)


def test_inprocess_mode_still_maps_errors(monkeypatch):
    monkeypatch.setenv("BOMAGENT_PARSE_SANDBOX", "inprocess")
    with pytest.raises(ExtractionError):
        extract_sandboxed("nested.pdf", make_nested_pdf())


def test_limits_have_their_own_environment_variables():
    limits = limits_from_env(
        {
            "BOMAGENT_KB_EXTRACT_MEMORY_MB": "256",
            "BOMAGENT_KB_EXTRACT_CPU_SECONDS": "7",
            "BOMAGENT_KB_EXTRACT_TIMEOUT_SECONDS": "9.5",
        }
    )
    assert limits == SandboxLimits(memory_bytes=256 * MiB, cpu_seconds=7, timeout_seconds=9.5)
    assert limits_from_env({}) == SandboxLimits()

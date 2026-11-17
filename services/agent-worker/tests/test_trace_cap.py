"""DATA-01/02: runs.trace is capped at the application level (unit tests, no database)."""

from __future__ import annotations

import json

import pytest

from bomagent_agent_worker.app import Settings
from bomagent_agent_worker.trace_cap import (
    DEFAULT_TRACE_MAX_BYTES,
    TRUNCATED_NODE,
    cap_trace,
    trace_size,
)
from bomagent_agents.contracts import TraceStep
from bomagent_agents.resume import RESUME_NODE


def _step(i: int, pad: int = 200) -> TraceStep:
    return TraceStep(node=f"node-{i}", duration_s=0.5, llm_calls=1, detail={"pad": "x" * pad})


def _steps(n: int, pad: int = 200) -> list[TraceStep]:
    return [_step(i, pad) for i in range(n)]


def test_small_trace_is_returned_untouched() -> None:
    steps = _steps(5)
    assert cap_trace(steps, DEFAULT_TRACE_MAX_BYTES) == steps


def test_oversized_trace_keeps_first_and_last_steps_and_marks_the_gap() -> None:
    steps = _steps(100)
    cap = 3000
    out = cap_trace(steps, cap)
    assert trace_size(out) <= cap
    assert out[0] == steps[0]
    assert out[-1] == steps[-1]
    markers = [s for s in out if s.node == TRUNCATED_NODE]
    assert len(markers) == 1
    kept = [s for s in out if s.node != TRUNCATED_NODE]
    assert markers[0].detail["dropped"] == len(steps) - len(kept)
    assert markers[0].detail["total"] == len(steps)
    assert 0 < len(kept) < len(steps)
    # kept steps are a head and a tail of the original, in order, with the marker between
    idx = out.index(markers[0])
    head, tail = out[:idx], out[idx + 1 :]
    assert head == steps[: len(head)]
    assert tail == steps[len(steps) - len(tail) :]


def test_truncation_is_deterministic() -> None:
    steps = _steps(80)
    a = [s.model_dump(mode="json") for s in cap_trace(steps, 2500)]
    b = [s.model_dump(mode="json") for s in cap_trace(list(steps), 2500)]
    assert json.dumps(a) == json.dumps(b)


def test_kept_steps_are_never_modified() -> None:
    steps = _steps(60)
    out = cap_trace(steps, 2500)
    for s in out:
        if s.node != TRUNCATED_NODE:
            assert s in steps


def test_resume_records_in_the_dropped_middle_survive() -> None:
    steps = _steps(100)
    resume = TraceStep(
        node=RESUME_NODE, duration_s=0.0, detail={"mode": "checkpoint", "attempt": 1}
    )
    steps[50] = resume
    out = cap_trace(steps, 3000)
    assert resume in out
    marker = next(s for s in out if s.node == TRUNCATED_NODE)
    kept = [s for s in out if s.node != TRUNCATED_NODE]
    assert marker.detail["dropped"] == len(steps) - len(kept)


def test_single_huge_step_still_yields_a_bounded_valid_trace() -> None:
    steps = [_step(0), _step(1, pad=50_000), _step(2)]
    out = cap_trace(steps, 1500)
    assert out[0] == steps[0]
    assert any(s.node == TRUNCATED_NODE for s in out)
    assert trace_size(out) <= 1500


def test_zero_disables_the_cap() -> None:
    steps = _steps(50)
    assert cap_trace(steps, 0) == steps


def test_setting_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOMAGENT_RUN_TRACE_MAX_BYTES", raising=False)
    assert Settings().run_trace_max_bytes == DEFAULT_TRACE_MAX_BYTES
    monkeypatch.setenv("BOMAGENT_RUN_TRACE_MAX_BYTES", "12345")
    assert Settings().run_trace_max_bytes == 12345

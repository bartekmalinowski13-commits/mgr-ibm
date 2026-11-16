"""Application metrics (audit OPS-02), recorded through the OpenTelemetry metrics API.

Instruments are created on first use and are no-ops until :func:`configure_telemetry` installs
a meter provider, so library code can record unconditionally. Labels are bounded on purpose:
``tenant`` appears only on LLM usage (needed for cost per organisation), failure codes are
truncated, and no free text is ever a label.

| metric | type | labels |
|---|---|---|
| ``bomagent_runs_total`` | counter | status, variant |
| ``bomagent_run_duration_s`` | histogram | variant |
| ``bomagent_llm_calls_total`` | counter | model |
| ``bomagent_llm_tokens_total`` | counter | model, tenant, direction |
| ``bomagent_llm_cost_eur_total`` | counter | model, tenant |
| ``bomagent_parse_total`` | counter | outcome, code |
| ``bomagent_parse_duration_s`` | histogram | - |
| ``bomagent_malware_scan_total`` | counter | outcome (clean, infected, error) |
| ``bomagent_malware_scan_duration_s`` | histogram | - |
| ``bomagent_outbox_sent_total`` / ``bomagent_outbox_dead_total`` | counter | - |
| ``bomagent_queue_dead_total`` | counter | queue |
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from opentelemetry import metrics

_MAX_LABEL = 64


def _label(value: object) -> str:
    return str(value)[:_MAX_LABEL] if value is not None else ""


@lru_cache(maxsize=1)
def _instruments() -> dict[str, Any]:
    meter = metrics.get_meter("bomagent")
    return {
        "runs": meter.create_counter("bomagent_runs_total", description="Finished agent runs"),
        "run_duration": meter.create_histogram(
            "bomagent_run_duration_s", unit="s", description="Wall time of an agent run"
        ),
        "llm_calls": meter.create_counter("bomagent_llm_calls_total", description="LLM calls"),
        "llm_tokens": meter.create_counter("bomagent_llm_tokens_total", description="LLM tokens"),
        "llm_cost": meter.create_counter(
            "bomagent_llm_cost_eur_total", unit="EUR", description="LLM spend"
        ),
        "parse": meter.create_counter("bomagent_parse_total", description="Design file parses"),
        "parse_duration": meter.create_histogram(
            "bomagent_parse_duration_s", unit="s", description="Wall time of a file parse"
        ),
        "malware_scan": meter.create_counter(
            "bomagent_malware_scan_total", description="Uploaded file malware scans"
        ),
        "malware_scan_duration": meter.create_histogram(
            "bomagent_malware_scan_duration_s", unit="s", description="Wall time of a malware scan"
        ),
        "outbox_sent": meter.create_counter(
            "bomagent_outbox_sent_total", description="Outbox messages delivered"
        ),
        "outbox_dead": meter.create_counter(
            "bomagent_outbox_dead_total", description="Outbox messages given up on"
        ),
        "queue_dead": meter.create_counter(
            "bomagent_queue_dead_total", description="Queue messages dead-lettered"
        ),
    }


def record_run(status: str, variant: str, *, duration_s: float) -> None:
    i = _instruments()
    i["runs"].add(1, {"status": _label(status), "variant": _label(variant)})
    if duration_s >= 0:
        i["run_duration"].record(duration_s, {"variant": _label(variant)})


def record_llm(
    *,
    model: str,
    tenant: str,
    llm_calls: int,
    input_tokens: int,
    output_tokens: int,
    cost_eur: float,
) -> None:
    i = _instruments()
    if llm_calls > 0:
        i["llm_calls"].add(llm_calls, {"model": _label(model)})
    base = {"model": _label(model), "tenant": _label(tenant)}
    if input_tokens > 0:
        i["llm_tokens"].add(input_tokens, {**base, "direction": "input"})
    if output_tokens > 0:
        i["llm_tokens"].add(output_tokens, {**base, "direction": "output"})
    if cost_eur > 0:
        i["llm_cost"].add(cost_eur, base)


def record_parse(outcome: str, code: str | None, *, duration_s: float) -> None:
    i = _instruments()
    i["parse"].add(1, {"outcome": _label(outcome), "code": _label(code)})
    if duration_s >= 0:
        i["parse_duration"].record(duration_s)


def record_malware_scan(outcome: str, *, duration_s: float) -> None:
    i = _instruments()
    i["malware_scan"].add(1, {"outcome": _label(outcome)})
    if duration_s >= 0:
        i["malware_scan_duration"].record(duration_s)


def record_outbox_sent(count: int = 1) -> None:
    if count > 0:
        _instruments()["outbox_sent"].add(count)


def record_outbox_dead() -> None:
    _instruments()["outbox_dead"].add(1)


def record_queue_dead(queue: str) -> None:
    _instruments()["queue_dead"].add(1, {"queue": _label(queue)})

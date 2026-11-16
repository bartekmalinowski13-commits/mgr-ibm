"""OTel metrics (audit OPS-02): names, labels and what lands in the reader."""

from __future__ import annotations

import pytest

from bomagent_common import metrics
from bomagent_common.config import ServiceSettings
from bomagent_common.telemetry import configure_telemetry, metric_reader


@pytest.fixture(autouse=True)
def _provider():
    configure_telemetry(ServiceSettings(service_name="test", environment="test"))


def _points(name: str) -> list[tuple[dict[str, object], float]]:
    """(attributes, value-or-sum) of every data point of ``name`` in the reader."""
    data = metric_reader().get_metrics_data()
    out: list[tuple[dict[str, object], float]] = []
    for rm in data.resource_metrics if data else []:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    for dp in m.data.data_points:
                        value = getattr(dp, "value", None)
                        out.append(
                            (dict(dp.attributes), float(value if value is not None else dp.sum))
                        )
    return out


def _delta(name: str, attrs: dict[str, object], before: list) -> float:
    def pick(points):
        return sum(v for a, v in points if a == attrs)

    return pick(_points(name)) - pick(before)


def test_runs_are_counted_by_status_and_variant_with_a_duration():
    before_runs = _points("bomagent_runs_total")
    before_dur = _points("bomagent_run_duration_s")
    metrics.record_run("completed", "B", duration_s=12.5)
    metrics.record_run("failed", "A", duration_s=3.0)
    assert _delta("bomagent_runs_total", {"status": "completed", "variant": "B"}, before_runs) == 1
    assert _delta("bomagent_runs_total", {"status": "failed", "variant": "A"}, before_runs) == 1
    assert _delta("bomagent_run_duration_s", {"variant": "B"}, before_dur) == 12.5


def test_llm_usage_is_split_by_model_direction_and_tenant():
    before_tok = _points("bomagent_llm_tokens_total")
    before_cost = _points("bomagent_llm_cost_eur_total")
    before_calls = _points("bomagent_llm_calls_total")
    metrics.record_llm(
        model="m1",
        tenant="t1",
        llm_calls=3,
        input_tokens=1000,
        output_tokens=200,
        cost_eur=0.25,
    )
    base = {"model": "m1", "tenant": "t1"}
    assert _delta("bomagent_llm_tokens_total", {**base, "direction": "input"}, before_tok) == 1000
    assert _delta("bomagent_llm_tokens_total", {**base, "direction": "output"}, before_tok) == 200
    assert _delta("bomagent_llm_cost_eur_total", base, before_cost) == pytest.approx(0.25)
    assert _delta("bomagent_llm_calls_total", {"model": "m1"}, before_calls) == 3


def test_parse_outcomes_and_failure_codes():
    before = _points("bomagent_parse_total")
    metrics.record_parse("ok", None, duration_s=0.4)
    metrics.record_parse("failed", "parse.timeout", duration_s=90.0)
    assert _delta("bomagent_parse_total", {"outcome": "ok", "code": ""}, before) == 1
    assert (
        _delta("bomagent_parse_total", {"outcome": "failed", "code": "parse.timeout"}, before) == 1
    )


def test_malware_scan_outcomes():
    before = _points("bomagent_malware_scan_total")
    metrics.record_malware_scan("clean", duration_s=0.01)
    metrics.record_malware_scan("infected", duration_s=0.02)
    assert _delta("bomagent_malware_scan_total", {"outcome": "clean"}, before) == 1
    assert _delta("bomagent_malware_scan_total", {"outcome": "infected"}, before) == 1


def test_reliability_counters():
    before_dead = _points("bomagent_outbox_dead_total")
    before_q = _points("bomagent_queue_dead_total")
    before_sent = _points("bomagent_outbox_sent_total")
    metrics.record_outbox_dead()
    metrics.record_queue_dead("runs")
    metrics.record_outbox_sent(4)
    assert _delta("bomagent_outbox_dead_total", {}, before_dead) == 1
    assert _delta("bomagent_queue_dead_total", {"queue": "runs"}, before_q) == 1
    assert _delta("bomagent_outbox_sent_total", {}, before_sent) == 4


def test_zero_or_negative_values_are_ignored_and_labels_are_bounded():
    before = _points("bomagent_llm_tokens_total")
    metrics.record_llm(
        model="m2", tenant="t", llm_calls=0, input_tokens=0, output_tokens=-5, cost_eur=0
    )
    assert (
        _delta(
            "bomagent_llm_tokens_total",
            {"model": "m2", "tenant": "t", "direction": "input"},
            before,
        )
        == 0
    )
    # a hostile failure code cannot mint unbounded label values
    before_parse = _points("bomagent_parse_total")
    metrics.record_parse("failed", "x" * 500, duration_s=0.1)
    codes = {a["code"] for a, _ in _points("bomagent_parse_total")} - {
        a["code"] for a, _ in before_parse
    }
    assert all(len(str(c)) <= 64 for c in codes)


def test_otlp_metric_exporter_is_wired_when_an_endpoint_is_configured():
    from bomagent_common import telemetry

    def kinds(env: str, endpoint: str | None) -> set[str]:
        readers = telemetry.build_metric_readers(
            ServiceSettings(service_name="t", environment=env, otel_exporter_otlp_endpoint=endpoint)
        )
        names = {type(r).__name__ for r in readers}
        for reader in readers:
            reader.shutdown()  # the periodic reader starts a thread on construction
        return names

    assert kinds("test", "http://c:4318") == {
        "InMemoryMetricReader",
        "PeriodicExportingMetricReader",
    }
    assert kinds("prod", "http://c:4318") == {"PeriodicExportingMetricReader"}  # no extra copy
    assert kinds("prod", None) == set()
    assert kinds("test", None) == {"InMemoryMetricReader"}

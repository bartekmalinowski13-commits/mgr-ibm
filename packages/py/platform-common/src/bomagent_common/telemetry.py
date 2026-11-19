"""OpenTelemetry setup (ADR-0010).

Traces and metrics go to an OTLP/HTTP collector (locally ``grafana/otel-lgtm``, in AWS the
ADOT collector, on the pilot Grafana Cloud EU). ``tenant.id`` is set on spans by
:func:`bomagent_common.tenancy.tenant_scope`. Metric names live in
:mod:`bomagent_common.metrics`; an in-memory reader is attached in local/test only.
GenAI calls use the semantic conventions ``gen_ai.*`` (see ``bomagent_llm``).
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine

    from bomagent_common.config import ServiceSettings

_provider: TracerProvider | None = None
_traced_engines: weakref.WeakSet[Engine] = weakref.WeakSet()
_metric_reader: InMemoryMetricReader | None = None
#: seconds between metric exports to the collector
METRIC_EXPORT_INTERVAL_MS = 30_000
#: an unreachable collector must not hold up shutdown (container stop grace periods)
EXPORT_TIMEOUT_S = 5
FLUSH_TIMEOUT_MS = 5_000


def metric_reader() -> InMemoryMetricReader:
    """The in-memory reader (cumulative values; local/test environments only)."""
    assert _metric_reader is not None, "no in-memory reader: configure_telemetry(local/test)"
    return _metric_reader


def build_metric_readers(settings: ServiceSettings) -> list[MetricReader]:
    # the in-memory reader serves tests and diagnostics only; production keeps no extra copy
    readers: list[MetricReader] = (
        [InMemoryMetricReader()] if settings.environment in {"local", "test"} else []
    )
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/metrics"
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint, timeout=EXPORT_TIMEOUT_S),
                export_interval_millis=METRIC_EXPORT_INTERVAL_MS,
            )
        )
    return readers


def configure_telemetry(
    settings: ServiceSettings, *, extra_exporter: SpanExporter | None = None
) -> TracerProvider:
    """Install a global tracer provider for this process (idempotent)."""
    global _provider, _metric_reader  # noqa: PLW0603 - process-wide singletons by design
    if _provider is not None:
        if extra_exporter is not None:
            _provider.add_span_processor(SimpleSpanProcessor(extra_exporter))
        return _provider

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "service.namespace": "bomagent",
            "deployment.environment.name": settings.environment,
            "cloud.region": settings.aws_region,
        }
    )
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    if settings.otel_console_exporter:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    if extra_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(extra_exporter))
    trace.set_tracer_provider(provider)
    readers = build_metric_readers(settings)
    _metric_reader = next((r for r in readers if isinstance(r, InMemoryMetricReader)), None)
    otel_metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
    _provider = provider
    return provider


def instrument_fastapi(app: FastAPI) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")


def instrument_sqlalchemy(engine: AsyncEngine) -> None:
    """Trace every statement of ``engine`` (ADR-0010); idempotent per engine.

    ``SQLAlchemyInstrumentor.instrument`` is a process-wide singleton that ignores every
    call after the first, so later engines get their own ``EngineTracer``. Statements are
    traced as written (bound values are never recorded)."""
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.instrumentation.sqlalchemy.engine import EngineTracer

    sync = engine.sync_engine
    if sync in _traced_engines:
        return
    _traced_engines.add(sync)
    instrumentor = SQLAlchemyInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        # the instrumentation declares "sqlalchemy < 2.1" and silently does nothing for 2.1;
        # the engine event API it hooks is unchanged in 2.1 (covered by test_api_hardening)
        instrumentor.instrument(engine=sync, skip_dep_check=True)
        return
    usage = otel_metrics.get_meter(
        "opentelemetry.instrumentation.sqlalchemy"
    ).create_up_down_counter(
        name="db.client.connections.usage",
        unit="connections",
        description="The number of connections that are currently in the state described by"
        " the state attribute.",
    )
    tracer = trace.get_tracer("opentelemetry.instrumentation.sqlalchemy")
    EngineTracer(tracer, sync, usage)  # type: ignore[no-untyped-call]  # untyped upstream


def instrument_httpx() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()


def shutdown_telemetry() -> None:
    if _provider is not None:
        _provider.force_flush(timeout_millis=FLUSH_TIMEOUT_MS)
    meter_provider = otel_metrics.get_meter_provider()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.force_flush(timeout_millis=FLUSH_TIMEOUT_MS)


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)

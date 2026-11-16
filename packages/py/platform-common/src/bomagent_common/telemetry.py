"""OpenTelemetry setup (ADR-0010).

Traces and metrics go to an OTLP/HTTP collector (locally ``grafana/otel-lgtm``, in AWS the
ADOT collector, on the pilot Grafana Cloud EU). ``tenant.id`` is set on spans by
:func:`bomagent_common.tenancy.tenant_scope`. Metric names live in
:mod:`bomagent_common.metrics`; an in-memory reader is always attached (tests, diagnostics).
GenAI calls use the semantic conventions ``gen_ai.*`` (see ``bomagent_llm``).
"""

from __future__ import annotations

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
    from sqlalchemy.ext.asyncio import AsyncEngine

    from bomagent_common.config import ServiceSettings

_provider: TracerProvider | None = None
_metric_reader: InMemoryMetricReader | None = None
#: seconds between metric exports to the collector
METRIC_EXPORT_INTERVAL_MS = 30_000


def metric_reader() -> InMemoryMetricReader:
    """The always-attached in-memory reader (cumulative values); needs ``configure_telemetry``."""
    assert _metric_reader is not None, "configure_telemetry() was not called"
    return _metric_reader


def build_metric_readers(settings: ServiceSettings) -> list[MetricReader]:
    readers: list[MetricReader] = [InMemoryMetricReader()]
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/metrics"
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint),
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
    _metric_reader = next(r for r in readers if isinstance(r, InMemoryMetricReader))
    otel_metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
    _provider = provider
    return provider


def instrument_fastapi(app: FastAPI) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")


def instrument_sqlalchemy(engine: AsyncEngine) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def instrument_httpx() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()


def shutdown_telemetry() -> None:
    if _provider is not None:
        _provider.force_flush()
    meter_provider = otel_metrics.get_meter_provider()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.force_flush()


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)

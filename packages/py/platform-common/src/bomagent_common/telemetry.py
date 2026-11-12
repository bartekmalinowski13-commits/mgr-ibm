"""OpenTelemetry setup (ADR-0010).

Traces go to an OTLP/HTTP collector (locally ``grafana/otel-lgtm``, in AWS the ADOT
collector). ``tenant.id`` is set on spans by :func:`bomagent_common.tenancy.tenant_scope`.
GenAI calls use the semantic conventions ``gen_ai.*`` (see ``bomagent_llm``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
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


def configure_telemetry(
    settings: ServiceSettings, *, extra_exporter: SpanExporter | None = None
) -> TracerProvider:
    """Install a global tracer provider for this process (idempotent)."""
    global _provider  # noqa: PLW0603 - process-wide singleton by design
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


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)

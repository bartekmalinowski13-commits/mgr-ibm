"""Liveness/readiness, tracing and problem+json for every deployable service."""

from __future__ import annotations

import importlib
from types import ModuleType

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from bomagent_common.telemetry import configure_telemetry

SERVICES = {
    "bomagent-api": "bomagent_api.app",
    "bomagent-ingest-worker": "bomagent_ingest.app",
    "bomagent-agent-worker": "bomagent_agent_worker.app",
    "bomagent-kb-indexer": "bomagent_kb_indexer.app",
}


@pytest.fixture(params=sorted(SERVICES), ids=lambda n: n.removeprefix("bomagent-"))
def service(request: pytest.FixtureRequest) -> tuple[str, ModuleType]:
    return request.param, importlib.import_module(SERVICES[request.param])


def _client(module: ModuleType, **settings: object) -> httpx.AsyncClient:
    app = module.create_app(module.Settings(environment="test", **settings))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_healthz_reports_service_and_version(service):
    name, module = service
    async with _client(module) as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": name, "version": "0.1.0"}


async def test_readyz_without_dependencies_is_ok(service):
    async with _client(service[1]) as client:
        assert (await client.get("/readyz")).status_code == 200


async def test_readyz_reports_unreachable_database(service):
    async with _client(
        service[1], database_url="postgresql+psycopg://nobody:x@127.0.0.1:1/none"
    ) as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": False}


async def test_requests_are_traced(service):
    exporter = InMemorySpanExporter()
    configure_telemetry(service[1].Settings(environment="test"), extra_exporter=exporter)
    async with _client(service[1]) as client:
        await client.get("/readyz")
    assert any("/readyz" in span.name for span in exporter.get_finished_spans())


async def test_unknown_route_returns_problem_json(service):
    async with _client(service[1]) as client:
        resp = await client.get("/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")

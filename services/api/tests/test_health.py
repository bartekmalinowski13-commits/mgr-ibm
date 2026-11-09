"""Liveness/readiness of bomagent-api and trace emission."""

from __future__ import annotations

import httpx
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from bomagent_api.app import Settings, create_app
from bomagent_common.telemetry import configure_telemetry


async def _client(settings: Settings) -> httpx.AsyncClient:
    app = create_app(settings)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_healthz_reports_service_and_version():
    async with await _client(Settings(environment="test")) as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["service"] == "bomagent-api"
    assert resp.json()["status"] == "ok"


async def test_readyz_without_dependencies_is_ok():
    async with await _client(Settings(environment="test")) as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 200


async def test_readyz_reports_unreachable_database():
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://nobody:x@127.0.0.1:1/none",
    )
    async with await _client(settings) as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": False}


async def test_requests_are_traced():
    exporter = InMemorySpanExporter()
    configure_telemetry(Settings(environment="test"), extra_exporter=exporter)
    async with await _client(Settings(environment="test")) as client:
        await client.get("/readyz")
    assert any("/readyz" in span.name for span in exporter.get_finished_spans())


async def test_unknown_route_returns_problem_json():
    async with await _client(Settings(environment="test")) as client:
        resp = await client.get("/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 404

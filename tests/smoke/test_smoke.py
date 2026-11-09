"""Smoke tests against a running stack (TESTING.md "Testy smoke").

Run with ``just smoke`` (local compose stack) or against an environment by setting the
``SMOKE_*`` URLs. Steps that need later milestones are added as those land.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.smoke

SERVICES = {
    "api": os.environ.get("SMOKE_API_URL", "http://localhost:8000"),
    "ingest-worker": os.environ.get("SMOKE_INGEST_URL", "http://localhost:8001"),
    "agent-worker": os.environ.get("SMOKE_AGENT_URL", "http://localhost:8002"),
    "kb-indexer": os.environ.get("SMOKE_KB_INDEXER_URL", "http://localhost:8003"),
}
GATEWAY_URL = os.environ.get("SMOKE_GATEWAY_URL", "http://localhost:4000")
TEMPO_URL = os.environ.get("SMOKE_TEMPO_URL")  # e.g. http://localhost:3200


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_service_health_and_readiness(name: str) -> None:
    base = SERVICES[name]
    assert httpx.get(f"{base}/healthz", timeout=5).json()["status"] == "ok"
    ready = httpx.get(f"{base}/readyz", timeout=10)
    assert ready.status_code == 200, ready.text


def test_gateway_is_alive() -> None:
    resp = httpx.get(f"{GATEWAY_URL}/health/liveliness", timeout=5)
    assert resp.status_code == 200


@pytest.mark.skipif(not TEMPO_URL, reason="SMOKE_TEMPO_URL not set (no trace backend)")
def test_api_request_trace_reaches_tempo() -> None:
    httpx.get(f"{SERVICES['api']}/readyz", timeout=5)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        resp = httpx.get(
            f"{TEMPO_URL}/api/search",
            params={"tags": "service.name=bomagent-api", "limit": 5},
            timeout=5,
        )
        if resp.status_code == 200 and resp.json().get("traces"):
            return
        time.sleep(3)
    pytest.fail("no bomagent-api trace visible in Tempo within 60 s")

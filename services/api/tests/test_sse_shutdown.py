"""Open live-progress streams end when the process shuts down, so uvicorn's wait for open
connections (and the lifespan teardown after it) is not held up for up to 15 minutes."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from bomagent_api.app import Settings, create_app
from bomagent_common.messaging import InMemoryQueue
from bomagent_common.shutdown import shutdown_of
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.api import mark_files_parsed
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


async def test_event_stream_ends_on_shutdown(app_engine, platform_engine):
    app = create_app(
        Settings(environment="test", auth_mode="local", sse_interval_s=5, sse_timeout_s=600),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues={"ingest": InMemoryQueue(), "runs": InMemoryQueue()},  # type: ignore[dict-item]
        kb=make_kb(),
    )
    s = uuid.uuid4().hex[:6]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a") as c:
        token = (
            await c.post(
                "/v1/dev/token",
                json={"sub": f"o-{s}", "email": f"o-{s}@x.eu", "email_verified": True},
            )
        ).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        org = await c.post("/v1/organizations", headers=auth, json={"name": s, "slug": f"sd-{s}"})
        owner = auth | {"X-Org-Id": org.json()["id"]}
        pid = (await c.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
        await c.post(f"/v1/projects/{pid}/files", headers=owner, files={"file": ("a.sch", b"x")})
        await mark_files_parsed(app_engine, owner["X-Org-Id"])
        run = await c.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
        run_id = run.json()["id"]  # stays queued: no worker runs

        stream = asyncio.create_task(c.get(f"/v1/runs/{run_id}/events", headers=owner))
        await asyncio.sleep(0.3)
        assert not stream.done()
        shutdown_of(app).request()
        resp = await asyncio.wait_for(stream, timeout=2)  # far less than the 5 s interval
    assert resp.text.rstrip().endswith('data: {"status": "shutdown"}')

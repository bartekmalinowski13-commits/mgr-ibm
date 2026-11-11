"""The local demo seed (`tools/devstack.py --seed`) builds a usable demo tenant."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid
from pathlib import Path

import httpx
import pytest

from bomagent_agent_worker.handler import RunWorker
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_api.app import Settings, create_app
from bomagent_common.messaging import InMemoryQueue, process_one
from bomagent_common.storage import InMemoryObjectStore
from bomagent_ingest.handler import IngestWorker
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES
from bomagent_testing.kb import make_kb

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import demo_seed


def test_subject_matches_the_web_app_mock_sign_in():
    # apps/web/src/lib/session.tsx: `dev-${email.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`
    assert demo_seed.dev_sub("Anna@MedTech-Demo.example") == "dev-anna-medtech-demo-example"


@pytest.mark.integration
async def test_seed_creates_projects_and_completed_runs(app_engine, platform_engine, monkeypatch):
    slug = f"medtech-demo-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(demo_seed, "DEMO_ORG", ("MedTech Demo", slug))
    monkeypatch.setattr(demo_seed, "DEMO_EMAIL", f"{slug}@medtech-demo.example")
    store = InMemoryObjectStore(enforce_tenant=False)
    queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue()}
    app = create_app(
        Settings(environment="test", auth_mode="local"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=store,
        queues=queues,  # type: ignore[arg-type]
        kb=make_kb(),
    )
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    handlers = {
        "ingest": IngestWorker(app_engine, store).handle,
        "runs": RunWorker(
            engine=app_engine,
            store=store,
            chat=FakeChat(heuristic_responder),
            kb=make_kb(),
            retriever_factory=lambda t, snap: retriever,
        ).handle,
    }

    async def drain_forever() -> None:
        while True:
            for name, queue in queues.items():
                for item in await queue.receive(max_messages=10):
                    await process_one(queue, item, handlers[name])
            await asyncio.sleep(0.05)

    worker = asyncio.create_task(drain_forever())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api"
        ) as client:
            result = await demo_seed.seed(client, timeout_s=60)
            headers = {"X-Org-Id": result.org_id}
            token = await client.post(
                "/v1/dev/token",
                json={
                    "sub": demo_seed.dev_sub(demo_seed.DEMO_EMAIL),
                    "email": demo_seed.DEMO_EMAIL,
                },
            )
            headers["Authorization"] = f"Bearer {token.json()['access_token']}"
            assert len(result.project_ids) == len(demo_seed.DEMO_PROJECTS)
            for run_id in result.run_ids:
                run = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
                assert run["status"] == "completed"
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker

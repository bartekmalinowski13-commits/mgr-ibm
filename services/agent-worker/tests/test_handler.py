"""agent-worker: run.requested -> design from S3 -> variant -> results + audit."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from bomagent_agent_worker.app import Settings, build_handler
from bomagent_agent_worker.handler import (
    RUN_REQUESTED,
    RejectedRunError,
    RunInProgressError,
    RunWorker,
)
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue, Message, RetryLaterError, process_one
from bomagent_common.storage import InMemoryObjectStore, tenant_key
from bomagent_common.tenancy import tenant_scope
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES, kicad_project_paths
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


def _counter(name: str, attrs: dict[str, str]) -> float:
    """Cumulative value of a counter data point in the in-memory metric reader."""
    from bomagent_common.config import ServiceSettings
    from bomagent_common.telemetry import configure_telemetry, metric_reader

    configure_telemetry(ServiceSettings(service_name="test", environment="test"))
    data = metric_reader().get_metrics_data()
    total = 0.0
    for rm in data.resource_metrics if data else []:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    total += sum(
                        float(dp.value) for dp in m.data.data_points if dict(dp.attributes) == attrs
                    )
    return total


async def _worker(app_engine, store):
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    return RunWorker(
        engine=app_engine,
        store=store,
        chat=FakeChat(heuristic_responder),
        kb=make_kb(),
        retriever_factory=lambda t, s: retriever,
        allow_unregistered=True,
    )


@pytest.mark.parametrize("variant", ["A", "B"])
async def test_run_requested_produces_bom_trace_and_audit(app_engine, make_tenant, variant):
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    keys = []
    for path in kicad_project_paths("pulse-ox"):
        key = tenant_key(tenant.tenant_id, "projects", "p1", path.name)
        store.objects[key] = path.read_bytes()
        keys.append(key)
    run_id = uuid.uuid4()
    worker = await _worker(app_engine, store)
    queue = InMemoryQueue()
    await queue.send(
        Message.create(
            RUN_REQUESTED, tenant, {"run_id": str(run_id), "variant": variant, "object_keys": keys}
        )
    )
    (item,) = await queue.receive()
    assert await process_one(queue, item, worker.handle)
    bom = json.loads(store.objects[tenant_key(tenant.tenant_id, "runs", str(run_id), "bom.json")])
    assert bom["variant"] == variant
    assert bom["items"]
    assert tenant_key(tenant.tenant_id, "runs", str(run_id), "trace.json") in store.objects
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        action = (await conn.execute(text("SELECT action FROM audit.events"))).scalar()
    assert action == "run.completed"


async def test_foreign_keys_are_rejected_and_other_messages_ignored(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    worker = await _worker(app_engine, InMemoryObjectStore(enforce_tenant=False))
    with pytest.raises(RejectedRunError):
        await worker.execute(
            Message.create(
                RUN_REQUESTED,
                a,
                {
                    "run_id": str(uuid.uuid4()),
                    "variant": "B",
                    "object_keys": [tenant_key(b.tenant_id, "x.kicad_sch")],
                },
            )
        )
    with pytest.raises(RejectedRunError, match="does not implement"):
        await worker.execute(
            Message.create(
                RUN_REQUESTED,
                a,
                {
                    "run_id": str(uuid.uuid4()),
                    "variant": "B",
                    "runtime": "langgraph_a",
                    "object_keys": [tenant_key(a.tenant_id, "x.kicad_sch")],
                },
            )
        )
    await worker.handle(Message.create("other.type", a))


def test_build_handler_wiring(db_urls):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        build_handler(Settings(environment="test"))
    fake = build_handler(Settings(environment="test", database_url=db_urls.app))
    assert isinstance(fake.__self__.chat, FakeChat)
    real = build_handler(
        Settings(
            environment="test",
            database_url=db_urls.app,
            llm_gateway_url="http://gw",
            llm_gateway_key="k",
        )
    )
    assert type(real.__self__.chat).__name__ == "GatewayChat"


async def _registered_run(app_engine, store, tenant, *, missing_object: bool = False):
    pid, rid = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, created_by)"
                " VALUES (:i, :t, 'p', 'u')"
            ),
            {"i": pid, "t": tenant.tenant_id},
        )
        for path in kicad_project_paths("pulse-ox"):
            key = tenant_key(tenant.tenant_id, "projects", str(pid), path.name)
            if not missing_object:
                store.objects[key] = path.read_bytes()
            await conn.execute(
                text(
                    "INSERT INTO projects.files (id, tenant_id, project_id, name, object_key,"
                    " sha256, size_bytes, created_by, status) VALUES (:i, :t, :p, :n, :k,"
                    " repeat('a', 64), 1, 'u', 'parsed')"
                ),
                {"i": uuid.uuid4(), "t": tenant.tenant_id, "p": pid, "n": path.name, "k": key},
            )
        await conn.execute(
            text(
                "INSERT INTO runs.runs (id, tenant_id, project_id, variant, runtime, model_id,"
                " created_by) VALUES (:r, :t, :p, 'B', 'langgraph_b', 'fake-closed', 'u')"
            ),
            {"r": rid, "t": tenant.tenant_id, "p": pid},
        )
    return rid


async def _state(app_engine, tenant, rid):
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        status, error = (
            await conn.execute(
                text("SELECT status, error FROM runs.runs WHERE id = :i"), {"i": rid}
            )
        ).one()
        actions = (
            await conn.execute(text("SELECT action FROM audit.events ORDER BY seq"))
        ).scalars()
        versions = (await conn.execute(text("SELECT count(*) FROM bom.versions"))).scalar()
    return status, error, list(actions), versions


async def test_registered_run_uses_database_and_redelivery_is_a_no_op(app_engine, make_tenant):
    tenant, other = await make_tenant(), await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant)
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    completed_before = _counter("bomagent_runs_total", {"status": "completed", "variant": "B"})
    # forged payload: another model, variant and someone else's files - all ignored
    forged = Message.create(
        RUN_REQUESTED,
        tenant,
        {
            "run_id": str(rid),
            "variant": "A",
            "model_id": "not-in-eu",
            "object_keys": [tenant_key(other.tenant_id, "x.kicad_sch")],
        },
    )
    with tenant_scope(tenant):
        result = await worker.execute(forged)
        assert result is not None
        assert result.bom.variant == "B"
        assert await worker.execute(forged) is None  # redelivered: not run again
    status, error, actions, versions = await _state(app_engine, tenant, rid)
    assert (status, error, versions) == ("completed", None, 1)
    assert actions.count("run.completed") == 1
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        runs, calls = (
            await conn.execute(text("SELECT runs, llm_calls FROM metering.usage_daily"))
        ).one()
    assert runs == 1  # metered once despite the redelivery
    assert calls == result.usage.llm_calls
    completed_after = _counter("bomagent_runs_total", {"status": "completed", "variant": "B"})
    assert completed_after - completed_before == 1  # counted once as well
    # checkpoints lived in the tenant's rows during the run and are gone after it
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        checkpoints = await conn.scalar(
            text("SELECT count(*) FROM runs.graph_checkpoints WHERE run_id = :r"), {"r": rid}
        )
    assert checkpoints == 0


async def test_failed_run_is_marked_failed_and_unknown_runs_rejected(app_engine, make_tenant):
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant, missing_object=True)
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    msg = Message.create(RUN_REQUESTED, tenant, {"run_id": str(rid)})
    failed = {"status": "failed", "variant": "B"}
    failed_before = _counter("bomagent_runs_total", failed)
    with tenant_scope(tenant), pytest.raises(Exception):  # noqa: B017, PT011
        await worker.execute(msg)
    assert _counter("bomagent_runs_total", failed) - failed_before == 1
    status, error, actions, _ = await _state(app_engine, tenant, rid)
    assert status == "failed"
    assert error.endswith("run failed")
    assert actions == ["run.failed"]
    assert await worker.execute(msg) is None
    with pytest.raises(RejectedRunError, match="unknown run"):
        await worker.execute(Message.create(RUN_REQUESTED, tenant, {"run_id": str(uuid.uuid4())}))


async def test_result_of_a_reaped_run_is_discarded_and_failed_spend_is_metered(
    app_engine, make_tenant
):
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant)
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    real_put = store.put

    async def reaped_meanwhile(key, data, content_type="application/octet-stream"):
        async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
            await conn.execute(
                text("UPDATE runs.runs SET status = 'failed' WHERE id = :i"), {"i": rid}
            )
        await real_put(key, data, content_type)

    store.put = reaped_meanwhile  # type: ignore[method-assign]
    with tenant_scope(tenant):
        result = await worker.execute(Message.create(RUN_REQUESTED, tenant, {"run_id": str(rid)}))
    assert result is not None
    status, _, actions, versions = await _state(app_engine, tenant, rid)
    assert (status, versions) == ("failed", 0)
    assert actions == ["run.result_discarded"]
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        runs, calls = (
            await conn.execute(text("SELECT runs, llm_calls FROM metering.usage_daily"))
        ).one()
    assert runs == 0
    assert calls == result.usage.llm_calls > 0

    # a failure after the LLM work still meters what was spent
    rid2 = await _registered_run(app_engine, store, tenant)

    async def broken_put(key, data, content_type="application/octet-stream"):
        raise OSError("object store unavailable")

    store.put = broken_put  # type: ignore[method-assign]
    with tenant_scope(tenant), pytest.raises(OSError, match="unavailable"):
        await worker.execute(Message.create(RUN_REQUESTED, tenant, {"run_id": str(rid2)}))
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        runs, calls = (
            await conn.execute(text("SELECT runs, llm_calls FROM metering.usage_daily"))
        ).one()
    assert runs == 1
    assert calls == 2 * result.usage.llm_calls


async def test_steps_reach_the_database_while_the_run_is_running(app_engine, make_tenant):
    """Live progress: each finished step is stored before the run ends (SSE polls it)."""
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant)
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    observed: list[tuple[str, int, int]] = []
    original = worker._progress

    async def spy(*args, **kwargs):
        await original(*args, **kwargs)
        async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
            status, steps, calls = (
                await conn.execute(
                    text(
                        "SELECT status, jsonb_array_length(trace),"
                        " coalesce((usage->>'llm_calls')::int, 0) FROM runs.runs WHERE id = :i"
                    ),
                    {"i": rid},
                )
            ).one()
        observed.append((status, steps, calls))

    worker._progress = spy
    message = Message.create(RUN_REQUESTED, tenant, {"run_id": str(rid)})
    with tenant_scope(tenant):
        result = await worker.execute(message)
    assert result is not None
    assert observed, "no progress was written"
    assert all(status == "running" for status, _, _ in observed)
    assert [steps for _, steps, _ in observed] == list(range(1, len(observed) + 1))
    assert len(observed) == len(result.trace)
    status, *_ = await _state(app_engine, tenant, rid)
    assert status == "completed"


class WorkerKilled(BaseException):
    """The worker dies mid-run: no failure handling runs, the run stays ``running``."""


class _DyingChat(FakeChat):
    async def complete(self, request):
        raise WorkerKilled


async def _crash_midway(app_engine, store, tenant, rid):
    """Run ``rid`` with a worker that dies at its first LLM call (after the first checkpoint)."""
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    worker.chat = _DyingChat(heuristic_responder)
    message = Message.create(RUN_REQUESTED, tenant, {"run_id": str(rid)})
    with tenant_scope(tenant), pytest.raises(WorkerKilled):
        await worker.execute(message)
    return message


async def _count_checkpoints(app_engine, tenant, rid) -> int:
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        return int(
            await conn.scalar(
                text("SELECT count(*) FROM runs.graph_checkpoints WHERE run_id = :r"), {"r": rid}
            )
            or 0
        )


async def test_crashed_run_is_resumed_from_its_checkpoint_and_says_so(app_engine, make_tenant):
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant)
    message = await _crash_midway(app_engine, store, tenant, rid)
    status, *_ = await _state(app_engine, tenant, rid)
    assert status == "running"
    assert await _count_checkpoints(app_engine, tenant, rid) >= 2  # graph + state snapshot

    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    # the worker still looks alive: the message is retried, nothing changes
    with tenant_scope(tenant), pytest.raises(RunInProgressError) as busy:
        await worker.execute(message)
    # ... once it would be stale, not after the rest of the queue's hour-long visibility
    assert 0 < busy.value.retry_after_s <= worker.resume_stale_after_s
    assert isinstance(busy.value, RetryLaterError)
    assert (await _state(app_engine, tenant, rid))[0] == "running"

    worker.resume_stale_after_s = 0.0  # the heartbeat went quiet
    with tenant_scope(tenant):
        result = await worker.execute(message)
    assert result is not None
    assert result.status == "completed"
    assert result.resumed is not None
    assert result.resumed.mode == "checkpoint"
    assert result.resumed.checkpoint_id
    assert result.resumed.attempt == 1
    assert [s.node for s in result.trace].count("run.resumed") == 1
    status, error, actions, versions = await _state(app_engine, tenant, rid)
    assert (status, error, versions) == ("completed", None, 1)
    assert actions.count("run.resumed") == 1
    assert actions.count("run.completed") == 1
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        after = (
            await conn.execute(
                text("SELECT after FROM audit.events WHERE action = 'run.completed'")
            )
        ).scalar_one()
        trace = (
            await conn.execute(text("SELECT trace FROM runs.runs WHERE id = :i"), {"i": rid})
        ).scalar_one()
    assert after["resumed"]["checkpoint_id"] == result.resumed.checkpoint_id
    assert after["resumed"]["previous_started_at"]
    assert any(step["node"] == "run.resumed" for step in trace)
    assert await _count_checkpoints(app_engine, tenant, rid) == 0  # cleaned up at the end

    # a second redelivery after completion is still a no-op
    with tenant_scope(tenant):
        assert await worker.execute(message) is None


async def test_run_that_keeps_dying_is_failed_after_the_resume_limit(app_engine, make_tenant):
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant)
    message = await _crash_midway(app_engine, store, tenant, rid)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text("UPDATE runs.runs SET trace = CAST(:t AS jsonb) WHERE id = :i"),
            {
                "t": json.dumps(
                    [{"node": "run.resumed", "duration_s": 0.0, "llm_calls": 0, "detail": {}}] * 3
                ),
                "i": rid,
            },
        )
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    worker.resume_stale_after_s = 0.0
    with tenant_scope(tenant):
        assert await worker.execute(message) is None
    status, error, actions, _ = await _state(app_engine, tenant, rid)
    assert status == "failed"
    assert error is not None
    assert "run.failed" in actions


def test_a_run_is_not_taken_for_dead_while_one_long_llm_call_is_in_flight():
    """The run's heartbeat is written between steps; a single chat call may legitimately take
    up to the per-call budget (``CALL_TIMEOUT_MAX_S``), so the stale threshold must exceed it."""
    from bomagent_llm.chat import CALL_TIMEOUT_MAX_S

    assert RunWorker.resume_stale_after_s > CALL_TIMEOUT_MAX_S
    assert Settings.model_fields["run_resume_stale_s"].default > CALL_TIMEOUT_MAX_S


async def test_an_interrupted_run_is_handed_back_once_it_can_be_resumed(monkeypatch):
    """Shutdown cancels the handler after a grace period: its message is released for
    redelivery once the run counts as stale (takeover then succeeds at once), not after the
    queue's 1 h visibility timeout; SIGTERM stops the consumer claiming new messages."""
    import asyncio

    from fastapi import FastAPI

    from bomagent_agent_worker import app as worker_app
    from bomagent_common.shutdown import shutdown_of

    seen: dict[str, object] = {}
    running = asyncio.Event()

    async def fake_consume(queue, handler, *, stop, release_delay_s, **kw):
        seen["release_delay_s"] = release_delay_s
        running.set()
        await stop.wait()
        seen["stopped_by_signal"] = True
        await asyncio.sleep(60)  # a handler that does not finish within the grace

    monkeypatch.setattr(worker_app, "consume_forever", fake_consume)
    settings = Settings(run_resume_stale_s=600, consumer_stop_grace_s=0.1)
    app = FastAPI()
    lifespan = worker_app._make_lifespan(settings, InMemoryQueue(), lambda m: None)  # type: ignore[arg-type]
    async with lifespan(app):
        await running.wait()
        shutdown_of(app).request()
        await asyncio.sleep(0.05)
        assert seen.get("stopped_by_signal") is True
    assert seen["release_delay_s"] == 600


def test_a_run_that_ends_failed_inside_the_graph_says_why():
    """A model failure is caught in the graph (``run.llm_error`` finding, status ``failed``);
    the run row needs a reason too, or the UI shows "the run failed: ." with nothing after."""
    from bomagent_agent_worker.handler import run_error
    from bomagent_bom.model import Finding, Severity

    def finding(rule: str, message: str) -> Finding:
        return Finding(rule_id=rule, severity=Severity.ERROR, message=message)

    issues = [
        finding("agent.mpn_rejected", "not a run problem"),
        finding("run.llm_error", "validate: gateway timed out after 608s"),
        finding("run.llm_error", "compose: gateway returned 500"),
    ]
    assert run_error("completed", issues) is None
    assert run_error("failed", issues) == "validate: gateway timed out after 608s (+1 more)"
    assert run_error("budget_exceeded", [finding("run.budget", "x" * 1000)]) == "x" * 300
    assert run_error("failed", []) == "failed"

"""Execute BOM runs from the ``runs`` queue (message ``run.requested``).

Payload: ``{run_id, variant, model_id, runtime?, object_keys: [...], requirements?}``.

Runs created through the API have a ``runs.runs`` row: the worker *claims* it atomically
(``queued`` -> ``running``) and takes variant, runtime, model, requirements and the design
files from the database, never from the message. SQS delivers at least once, so a
redelivered message for a run that is already running or finished is acknowledged
without running (and paying for) the LLM pipeline again. A failure marks the run
``failed`` with an audit event. Messages without a row (CLI, tests) are accepted only
when ``allow_unregistered`` is set (local/test environments).

Resume (ARCH-05): a redelivered message for a ``running`` run whose last checkpoint/state
write is older than ``resume_stale_after_s`` takes the run over and continues it from its
last checkpoint (``run.resumed`` audit event, ``run.resumed`` trace marker, ``resumed`` in the
final audit event); a run that still looks alive is retried later (message not acked).

Results: ``bom.json`` and ``trace.json`` under ``tenants/{tenant}/runs/{run_id}/``,
version 1 in ``bom.versions`` and ``run.<status>`` in the tenant's audit chain.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_agent_worker.trace_cap import DEFAULT_TRACE_MAX_BYTES, cap_trace
from bomagent_agents import resume
from bomagent_agents.checkpoint import TenantCheckpointSaver
from bomagent_agents.contracts import ResumeRecord, RunConfig, RunInput, RunOutput, TraceStep
from bomagent_agents.registry import context_factory, runtime_for
from bomagent_agents.retrieval import KbRetriever, Retriever
from bomagent_bom.model import Finding, Requirements, Usage
from bomagent_cad import FileRef
from bomagent_cad.sandbox import ProjectSize, parse_files_sandboxed
from bomagent_common import metrics
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.metering import record_usage
from bomagent_common.storage import ObjectStore, key_belongs_to, tenant_key
from bomagent_kb import KnowledgeBase
from bomagent_llm.chat import ChatClient

log = get_logger(__name__)
RUN_REQUESTED = "run.requested"
RUNTIME_VARIANT = {"langgraph_a": "A", "claude_agent_sdk_a": "A", "langgraph_b": "B"}


ERROR_MAX_CHARS = 300


def run_error(status: str, issues: list[Finding]) -> str | None:
    """Why a run that finished inside the graph is not ``completed``: the first ``run.*``
    finding (model failure or budget stop; their messages are ours, never file content)."""
    if status == "completed":
        return None
    reasons = [f.message for f in issues if f.rule_id.startswith("run.")]
    if not reasons:
        return status
    more = f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""
    return reasons[0][:ERROR_MAX_CHARS] + more


class RejectedRunError(ValueError):
    pass


class RunInProgressError(RuntimeError):
    """The run is ``running`` and its worker still looks alive (or another worker is taking
    it over): the message is not acknowledged, so the queue redelivers it later."""


@dataclass
class RunWorker:
    engine: AsyncEngine
    store: ObjectStore
    chat: ChatClient
    kb: KnowledgeBase
    retriever_factory: Callable[[uuid.UUID, str | None], Retriever] | None = None
    allow_unregistered: bool = False
    #: a ``running`` run without a checkpoint/state write for this long is taken to have lost
    #: its worker and is resumed on redelivery (must exceed the longest single step: one LLM
    #: call may take up to ``bomagent_llm.chat.CALL_TIMEOUT_MAX_S``)
    resume_stale_after_s: float = 1200.0
    max_resumes: int = 3
    #: size cap of ``runs.trace`` (DATA-01/02); the full trace stays in ``trace.json``
    trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES

    def _retriever(self, tenant_id: uuid.UUID, snapshot: str | None) -> Retriever:
        if self.retriever_factory is not None:
            return self.retriever_factory(tenant_id, snapshot)
        return KbRetriever(self.kb, self.engine, tenant_id, snapshot)

    async def handle(self, message: Message) -> None:
        if message.type != RUN_REQUESTED:
            log.warning("message_type_ignored", message_type=message.type)
            return
        await self.execute(message)

    async def _claim(self, message: Message, run_id: uuid.UUID) -> dict[str, Any] | None:
        """Run parameters from the database (``queued`` -> ``running``), the message
        payload for unregistered runs, or ``None`` when the run is already taken."""
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE runs.runs SET status = 'running', started_at = now()"
                        " WHERE id = :i AND status = 'queued'"
                        " RETURNING project_id, variant, runtime, model_id, requirements,"
                        " kb_snapshot_id"
                    ),
                    {"i": run_id},
                )
            ).first()
            if row is not None:
                return await self._params(conn, row)
            seen = (
                await conn.execute(
                    text("SELECT status, started_at, now() AS now FROM runs.runs WHERE id = :i"),
                    {"i": run_id},
                )
            ).first()
        if seen is not None:
            if seen.status == "running":
                return await self._takeover(message, run_id, seen.started_at, seen.now)
            log.info("run_already_claimed", run_id=str(run_id), status=seen.status)
            return None
        if not self.allow_unregistered:
            raise RejectedRunError("unknown run (no runs.runs row in this tenant)")
        return dict(message.payload) | {"registered": False}

    @staticmethod
    async def _params(conn: AsyncConnection, row: Any) -> dict[str, Any]:
        keys = (
            await conn.execute(
                text(
                    "SELECT object_key FROM projects.files"
                    " WHERE project_id = :p AND status = 'parsed' ORDER BY name"
                ),
                {"p": row.project_id},
            )
        ).scalars()
        return {
            "variant": row.variant,
            "runtime": row.runtime,
            "model_id": row.model_id,
            "requirements": row.requirements,
            "kb_snapshot_id": row.kb_snapshot_id,
            "object_keys": list(keys),
            "registered": True,
        }

    async def _takeover(
        self, message: Message, run_id: uuid.UUID, started_at: Any, now: Any
    ) -> dict[str, Any] | None:
        """Redelivery for a ``running`` run (ARCH-05): if nothing was written for
        ``resume_stale_after_s`` its worker is taken to be dead and this worker continues the
        run from the last checkpoint; otherwise the message is retried later.

        Takeover is a compare-and-swap on ``started_at`` (reset to now: the reaper's clock
        restarts), so two workers never resume the same run; the original start time is kept
        in the resume record."""
        saver = TenantCheckpointSaver(self.engine, message.tenant_id)
        last = await saver.last_activity(run_id)
        idle_s = (now - max(started_at, last or started_at)).total_seconds()
        if idle_s < self.resume_stale_after_s:
            raise RunInProgressError(f"run {run_id} is running (idle {idle_s:.0f}s)")
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE runs.runs SET started_at = now()"
                        " WHERE id = :i AND status = 'running' AND started_at = :s"
                        " RETURNING project_id, variant, runtime, model_id, requirements,"
                        " kb_snapshot_id,"
                        " (SELECT count(*) FROM jsonb_array_elements(trace) t"
                        "  WHERE t->>'node' = :n) AS resumes"
                    ),
                    {"i": run_id, "s": started_at, "n": resume.RESUME_NODE},
                )
            ).first()
            if row is None:  # finished, reaped or taken over by another worker meanwhile
                raise RunInProgressError(f"run {run_id} changed while taking it over")
            if row.resumes >= self.max_resumes:
                params = None
            else:
                params = await self._params(conn, row)
                params["resume"] = {
                    "attempt": int(row.resumes) + 1,
                    "previous_started_at": started_at.isoformat(),
                }
        if params is None:
            exc = RuntimeError("resume limit reached")
            await self._fail(message, run_id, exc, None)
            log.warning("run_resume_limit", run_id=str(run_id))
            return None
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            await emit_audit(
                conn,
                AuditEvent(
                    action="run.resumed",
                    object_type="run",
                    object_id=str(run_id),
                    after={**params["resume"], "idle_s": round(idle_s)},
                ),
            )
        log.info("run_resuming", run_id=str(run_id), attempt=params["resume"]["attempt"])
        return params

    async def _fail(
        self,
        message: Message,
        run_id: uuid.UUID,
        exc: BaseException,
        usage: Usage | None,
        *,
        variant: str = "",
        model: str = "",
        duration_s: float = 0.0,
    ) -> None:
        error = f"{type(exc).__name__}: run failed"  # no exception text: it may echo file content
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            updated = await conn.execute(
                text(
                    "UPDATE runs.runs SET status = 'failed', finished_at = now(), error = :e"
                    " WHERE id = :i AND status = 'running'"
                ),
                {"e": error, "i": run_id},
            )
            # LLM spend counts against the budget even when the run failed afterwards
            await _meter(conn, usage, runs=1 if updated.rowcount else 0)
            failed = bool(updated.rowcount)  # else already failed (e.g. by the reaper)
            if failed:
                await emit_audit(
                    conn,
                    AuditEvent(
                        action="run.failed",
                        object_type="run",
                        object_id=str(run_id),
                        after={"error": error},
                    ),
                )
        # metrics only after the commit: a rolled-back transaction must not be counted
        _observe(usage, model=model, tenant=message.tenant_id)
        if failed:
            metrics.record_run("failed", variant, duration_s=duration_s)

    async def execute(self, message: Message) -> RunOutput | None:
        run_id = uuid.UUID(message.payload["run_id"])
        p = await self._claim(message, run_id)
        if p is None:
            return None
        spent: dict[str, Usage] = {}
        started = time.monotonic()
        try:
            return await self._run(message, run_id, p, spent)
        except Exception as exc:
            if p["registered"]:
                await self._fail(
                    message,
                    run_id,
                    exc,
                    spent.get("usage"),
                    variant=str(p.get("variant", "")),
                    model=str(p.get("model_id", "")),
                    duration_s=time.monotonic() - started,
                )
            raise

    async def _progress(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, step: TraceStep, usage: Usage
    ) -> None:
        """Append a finished step to the running run (the API's SSE stream polls it)."""
        async with tenant_transaction(self.engine, tenant_id) as conn:
            await conn.execute(
                text(
                    "UPDATE runs.runs SET trace = trace || CAST(:s AS jsonb),"
                    " usage = CAST(:u AS jsonb) WHERE id = :i AND status = 'running'"
                ),
                {
                    "s": json.dumps([step.model_dump(mode="json")]),
                    "u": usage.model_dump_json(),
                    "i": run_id,
                },
            )

    async def _invoke(
        self,
        message: Message,
        run_id: uuid.UUID,
        run: RunInput,
        p: dict[str, Any],
        runtime: str | None,
        on_step: Callable[[TraceStep, Usage], Awaitable[None]],
    ) -> RunOutput:
        config = run.config
        saver = TenantCheckpointSaver(self.engine, message.tenant_id) if p["registered"] else None
        resume_info: dict[str, Any] | None = p.get("resume")
        factory = context_factory(
            self.chat,
            self._retriever(message.tenant_id, config.kb_snapshot_id),
            tenant_id=str(message.tenant_id),
            on_step=on_step if p["registered"] else None,
            # graph state in the tenant's own rows (RLS) while the run executes; CLI runs
            # have no run row and keep the in-memory checkpointer
            checkpointer=(lambda _run: saver) if saver is not None else None,
            state_store=(lambda _run: saver) if saver is not None else None,
            resume=resume_info is not None,
            resume_attempt=int(resume_info["attempt"]) if resume_info else 1,
        )
        try:
            result = await runtime_for(config.variant, factory, runtime=runtime).run(run)
        except Exception:
            # a failed run is final (``execute`` marks it failed): keep customer design state
            # no longer than the run. A cancelled worker (shutdown) leaves the run ``running``
            # with its checkpoints, so a redelivery resumes it (ARCH-05).
            if saver is not None:
                await saver.adelete_thread(str(run_id))
            raise
        if saver is not None:
            await saver.adelete_thread(str(run_id))  # data minimisation: done with the run
        if resume_info is not None and result.resumed is None:
            # a runtime without checkpoints (claude_agent_sdk_a) ran again from scratch
            result.resumed = ResumeRecord(mode="restart", attempt=int(resume_info["attempt"]))
            marker = TraceStep(
                node=resume.RESUME_NODE,
                duration_s=0.0,
                detail=result.resumed.model_dump(mode="json"),
            )
            result.trace.insert(0, marker)
        return result

    async def _run(
        self, message: Message, run_id: uuid.UUID, p: dict[str, Any], spent: dict[str, Usage]
    ) -> RunOutput:
        t0 = time.monotonic()
        runtime = p.get("runtime")
        if runtime is not None and RUNTIME_VARIANT.get(runtime) != p["variant"]:
            raise RejectedRunError(f"runtime {runtime!r} does not implement variant {p['variant']}")
        keys = [str(k) for k in p["object_keys"]]
        if not keys or not all(key_belongs_to(message.tenant_id, k) for k in keys):
            raise RejectedRunError("design files must be under the tenant prefix")
        budget = ProjectSize()  # bounded memory per run (the claim checked the tenant)
        files: list[FileRef] = []
        for k in keys:
            data = await self.store.get(k)
            budget.add(k.rsplit("/", 1)[-1], len(data))
            files.append(FileRef(k.rsplit("/", 1)[-1], data))
        # CPU-bound and untrusted input: resource-limited subprocess, off the event loop
        design = await asyncio.to_thread(parse_files_sandboxed, files)
        config = RunConfig(
            variant=p["variant"],
            model_id=p.get("model_id", "fake-closed"),
            kb_snapshot_id=p.get("kb_snapshot_id"),
        )
        run = RunInput(
            run_id=run_id,
            design=design,
            config=config,
            requirements=Requirements.model_validate(p.get("requirements") or {}),
        )
        # live progress: steps finish concurrently (fan-out), writes stay in order
        progress_lock = asyncio.Lock()

        async def on_step(step: TraceStep, usage: Usage) -> None:
            # spend so far, so a run that raises inside the runtime still meters its calls
            # (a step that raises reports here too, from ``AgentContext.step``'s finally)
            spent["usage"] = usage
            async with progress_lock:
                await self._progress(message.tenant_id, run_id, step, usage)

        result = await self._invoke(message, run_id, run, p, runtime, on_step)
        resume_info: dict[str, Any] | None = p.get("resume")
        spent["usage"] = result.usage
        base = (message.tenant_id, "runs", str(run_id))
        await self.store.put(
            tenant_key(*base, "bom.json"), result.bom.model_dump_json().encode(), "application/json"
        )
        await self.store.put(
            tenant_key(*base, "trace.json"),
            json.dumps([s.model_dump(mode="json") for s in result.trace]).encode(),
            "application/json",
        )
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            updated = await conn.execute(
                text(
                    "UPDATE runs.runs SET status = :s, finished_at = now(),"
                    " usage = CAST(:u AS jsonb), trace = CAST(:t AS jsonb),"
                    " kb_snapshot_id = :k, error = :e WHERE id = :i AND status = 'running'"
                ),
                {
                    "s": result.status,
                    "e": run_error(result.status, result.bom.findings),
                    "u": result.usage.model_dump_json(),
                    "t": json.dumps(
                        [
                            s.model_dump(mode="json")
                            for s in cap_trace(result.trace, self.trace_max_bytes)
                        ]
                    ),
                    "k": config.kb_snapshot_id,
                    "i": run_id,
                },
            )
            discarded = p["registered"] and not updated.rowcount
            if discarded:
                # the reaper failed the run meanwhile: keep the row as it is, meter the spend
                await _meter(conn, result.usage, runs=0)
                await emit_audit(
                    conn,
                    AuditEvent(
                        action="run.result_discarded",
                        object_type="run",
                        object_id=str(run_id),
                        after={"status": result.status, "reason": "run no longer running"},
                    ),
                )
            else:
                await _meter(conn, result.usage, runs=1)
            if not discarded:
                if updated.rowcount:  # API runs have a row; CLI runs do not
                    await conn.execute(
                        text(
                            "INSERT INTO bom.versions (id, tenant_id, run_id, version, content,"
                            " reason, created_by) VALUES (:i, app.current_tenant_id(), :r, 1,"
                            " CAST(:c AS jsonb), 'generated', :u)"
                        ),
                        {
                            "i": uuid.uuid4(),
                            "r": run_id,
                            "c": result.bom.model_dump_json(),
                            "u": f"agent:{result.runtime}",
                        },
                    )
                await emit_audit(
                    conn,
                    AuditEvent(
                        action=f"run.{result.status}",
                        object_type="run",
                        object_id=str(run_id),
                        after={
                            "status": result.status,
                            "variant": config.variant,
                            "model": config.model_id,
                            "runtime": result.runtime,
                            "lines": len(result.bom.items),
                            "llm_calls": result.usage.llm_calls,
                            **(
                                {
                                    "resumed": result.resumed.model_dump(mode="json")
                                    | {"previous_started_at": resume_info["previous_started_at"]}
                                }
                                if result.resumed is not None and resume_info is not None
                                else {}
                            ),
                        },
                    ),
                )
        # metrics only after the commit: a rolled-back transaction must not be counted (a
        # failure above makes ``execute`` run ``_fail``, which observes the same spend once)
        _observe(result.usage, model=config.model_id, tenant=message.tenant_id)
        if discarded:
            log.warning("run_result_discarded", run_id=str(run_id))
            return result
        metrics.record_run(result.status, config.variant, duration_s=time.monotonic() - t0)
        log.info(
            "run_finished",
            run_id=str(run_id),
            status=result.status,
            llm_calls=result.usage.llm_calls,
        )
        return result


async def _meter(conn: AsyncConnection, usage: Usage | None, *, runs: int) -> None:
    u = usage or Usage()
    await record_usage(
        conn,
        runs=runs,
        llm_calls=u.llm_calls,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cost_eur=u.cost_eur,
    )


def _observe(usage: Usage | None, *, model: str, tenant: uuid.UUID) -> None:
    """LLM spend as metrics; call once per metered spend, after its transaction committed."""
    u = usage or Usage()
    metrics.record_llm(
        model=model,
        tenant=str(tenant),
        llm_calls=u.llm_calls,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cost_eur=u.cost_eur,
    )

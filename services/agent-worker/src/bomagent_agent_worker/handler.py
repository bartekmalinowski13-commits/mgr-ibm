"""Execute BOM runs from the ``runs`` queue (message ``run.requested``).

Payload: ``{run_id, variant, model_id, runtime?, object_keys: [...], requirements?}``.

Runs created through the API have a ``runs.runs`` row: the worker *claims* it atomically
(``queued`` -> ``running``) and takes variant, runtime, model, requirements and the design
files from the database, never from the message. SQS delivers at least once, so a
redelivered message for a run that is already running or finished is acknowledged
without running (and paying for) the LLM pipeline again. A failure marks the run
``failed`` with an audit event. Messages without a row (CLI, tests) are accepted only
when ``allow_unregistered`` is set (local/test environments).

Results: ``bom.json`` and ``trace.json`` under ``tenants/{tenant}/runs/{run_id}/``,
version 1 in ``bom.versions`` and ``run.<status>`` in the tenant's audit chain.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_agents.contracts import RunConfig, RunInput, RunOutput
from bomagent_agents.registry import context_factory, runtime_for
from bomagent_agents.retrieval import KbRetriever, Retriever
from bomagent_bom.model import Requirements
from bomagent_cad import FileRef, parse_files
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.storage import ObjectStore, key_belongs_to, tenant_key
from bomagent_kb import KnowledgeBase
from bomagent_llm.chat import ChatClient

log = get_logger(__name__)
RUN_REQUESTED = "run.requested"
RUNTIME_VARIANT = {"langgraph_a": "A", "claude_agent_sdk_a": "A", "langgraph_b": "B"}


class RejectedRunError(ValueError):
    pass


@dataclass
class RunWorker:
    engine: AsyncEngine
    store: ObjectStore
    chat: ChatClient
    kb: KnowledgeBase
    retriever_factory: Callable[[uuid.UUID, str | None], Retriever] | None = None
    allow_unregistered: bool = False

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
                        " RETURNING project_id, variant, runtime, model_id, requirements"
                    ),
                    {"i": run_id},
                )
            ).first()
            if row is not None:
                keys = (
                    await conn.execute(
                        text(
                            "SELECT object_key FROM projects.files"
                            " WHERE project_id = :p ORDER BY name"
                        ),
                        {"p": row.project_id},
                    )
                ).scalars()
                return {
                    "variant": row.variant,
                    "runtime": row.runtime,
                    "model_id": row.model_id,
                    "requirements": row.requirements,
                    "object_keys": list(keys),
                    "registered": True,
                }
            exists = (
                await conn.execute(
                    text("SELECT status FROM runs.runs WHERE id = :i"), {"i": run_id}
                )
            ).scalar()
        if exists is not None:
            log.info("run_already_claimed", run_id=str(run_id), status=exists)
            return None
        if not self.allow_unregistered:
            raise RejectedRunError("unknown run (no runs.runs row in this tenant)")
        return dict(message.payload) | {"registered": False}

    async def _fail(self, message: Message, run_id: uuid.UUID, exc: BaseException) -> None:
        error = f"{type(exc).__name__}: run failed"  # no exception text: it may echo file content
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            await conn.execute(
                text(
                    "UPDATE runs.runs SET status = 'failed', finished_at = now(), error = :e"
                    " WHERE id = :i AND status = 'running'"
                ),
                {"e": error, "i": run_id},
            )
            await emit_audit(
                conn,
                AuditEvent(
                    action="run.failed",
                    object_type="run",
                    object_id=str(run_id),
                    after={"error": error},
                ),
            )

    async def execute(self, message: Message) -> RunOutput | None:
        run_id = uuid.UUID(message.payload["run_id"])
        p = await self._claim(message, run_id)
        if p is None:
            return None
        try:
            return await self._run(message, run_id, p)
        except Exception as exc:
            if p["registered"]:
                await self._fail(message, run_id, exc)
            raise

    async def _run(self, message: Message, run_id: uuid.UUID, p: dict[str, Any]) -> RunOutput:
        runtime = p.get("runtime")
        if runtime is not None and RUNTIME_VARIANT.get(runtime) != p["variant"]:
            raise RejectedRunError(f"runtime {runtime!r} does not implement variant {p['variant']}")
        keys = [str(k) for k in p["object_keys"]]
        if not keys or not all(key_belongs_to(message.tenant_id, k) for k in keys):
            raise RejectedRunError("design files must be under the tenant prefix")
        files = [FileRef(k.rsplit("/", 1)[-1], await self.store.get(k)) for k in keys]
        design = parse_files(files)
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
        factory = context_factory(
            self.chat,
            self._retriever(message.tenant_id, config.kb_snapshot_id),
            tenant_id=str(message.tenant_id),
        )
        result = await runtime_for(config.variant, factory, runtime=runtime).run(run)
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
                    " kb_snapshot_id = :k WHERE id = :i AND status = 'running'"
                ),
                {
                    "s": result.status,
                    "u": result.usage.model_dump_json(),
                    "t": json.dumps([s.model_dump(mode="json") for s in result.trace]),
                    "k": config.kb_snapshot_id,
                    "i": run_id,
                },
            )
            if updated.rowcount:  # runs started through the API have a row; CLI runs do not
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
                    },
                ),
            )
        log.info(
            "run_finished",
            run_id=str(run_id),
            status=result.status,
            llm_calls=result.usage.llm_calls,
        )
        return result

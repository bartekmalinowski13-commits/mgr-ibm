"""Runs (variant A/B), BOM versions, corrections, evaluation and export (ARCH-04)."""

from __future__ import annotations

import csv
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_api import idempotency
from bomagent_api.pagination import clamp, encode_cursor, page_filter
from bomagent_api.plans import check_new_run
from bomagent_api.repositories import projects as projects_repo
from bomagent_api.repositories import runs as repo
from bomagent_api.repositories.tables import runs as runs_table
from bomagent_api.schemas import (
    BomDiffOut,
    BomFieldChange,
    BomItemPatch,
    BomLineChange,
    BomVersionInfo,
    Counts,
    Evaluation,
    FieldAccuracy,
    ModelOption,
    Page,
    ReferenceDiff,
    Run,
    RunCreate,
    RunStep,
)
from bomagent_api.services.outbox import deliver_now
from bomagent_api.services.projects import get_project
from bomagent_bom.diff import diff_versions
from bomagent_bom.export import to_csv, to_xlsx
from bomagent_bom.model import BomVersion, Provenance, ProvenanceKind, Requirements
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message, Queue
from bomagent_common.outbox import enqueue
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext
from bomagent_eval.metrics import evaluate
from bomagent_eval.reference import load_reference_csv
from bomagent_kb import KnowledgeBase
from bomagent_llm.catalog import Catalog, ModelNotAllowedError

TERMINAL = {"completed", "failed", "budget_exceeded"}
DEFAULT_RUNTIME = {"A": "langgraph_a", "B": "langgraph_b"}
CANCELLED = "cancelled by user"


@dataclass(frozen=True)
class RunDeps:
    """What starting a run needs from the application (``app.state`` in the HTTP layer)."""

    engine: AsyncEngine
    queues: Mapping[str, Queue]
    kb: KnowledgeBase
    catalog: Catalog
    allow_local_models: bool


@dataclass(frozen=True)
class ExportedBom:
    version: int
    kb_snapshot_id: str | None
    content: str | bytes


def _run_not_found() -> ProblemError:
    return ProblemError(404, "Not Found", "run not found", slug="not-found")


async def get_run(conn: AsyncConnection, run_id: uuid.UUID) -> dict[str, Any]:
    row = await repo.get(conn, run_id)
    if row is None:
        raise _run_not_found()
    return row


def check_model_allowed(deps: RunDeps, model_id: str) -> None:
    try:
        deps.catalog.get(model_id, allow_local=deps.allow_local_models)
    except ModelNotAllowedError as exc:
        raise ProblemError(422, "Unprocessable Entity", str(exc), slug="model-not-allowed") from exc


def resolve_runtime(variant: str, runtime: str | None) -> str:
    """The runtime of a run request; it must implement the requested variant."""
    chosen = runtime or DEFAULT_RUNTIME[variant]
    if chosen.endswith("_a") != (variant == "A"):
        raise ProblemError(
            422,
            "Unprocessable Entity",
            f"runtime {chosen} does not implement variant {variant}",
            slug="runtime-variant",
        )
    return chosen


def list_models(catalog: Catalog, allow_local: bool) -> list[ModelOption]:
    """The catalogue entries a run may use (enabled, verified, EU; local fakes only in
    local/test) - the same rule ``create_run`` enforces."""
    return [
        ModelOption(
            id=m.id,
            provider=m.provider,
            license_class=m.license_class.value,
            residency=m.residency,
            tier=m.tier,
        )
        for m in catalog.enabled("chat")
        if allow_local or m.residency != "local"
    ]


async def start_run(
    deps: RunDeps,
    ctx: TenantContext,
    conn: AsyncConnection,
    *,
    project_id: uuid.UUID,
    variant: str,
    runtime: str,
    model_id: str,
    requirements: dict[str, Any],
    audit_extra: dict[str, Any] | None = None,
) -> tuple[Run, uuid.UUID]:
    """Insert a queued run for the project's parsed files and queue it (outbox). Shared by
    ``create_run`` and re-execution; the caller delivers the outbox message after commit."""
    await get_project(conn, project_id)
    await check_new_run(conn)
    keys = await projects_repo.parsed_object_keys(conn, project_id)
    if not keys:
        raise ProblemError(
            409,
            "Conflict",
            "upload design files and wait until they are checked before starting a run",
            slug="no-files",
        )
    rid = uuid.uuid4()
    # ADR-0008 / R10: pin the run to the tenant's knowledge base as it is now. The snapshot id
    # is a hash of the active documents, so an unchanged KB reuses the existing row.
    kb_snapshot_id = await deps.kb.snapshot(conn)
    await repo.insert_run(
        conn,
        run_id=rid,
        project_id=project_id,
        variant=variant,
        runtime=runtime,
        model_id=model_id,
        requirements=requirements,
        kb_snapshot_id=kb_snapshot_id,
        created_by=ctx.actor_id,
    )
    run = Run(**await get_run(conn, rid))
    await emit_audit(
        conn,
        AuditEvent(
            action="run.created",
            object_type="run",
            object_id=str(rid),
            after={
                "variant": variant,
                "runtime": runtime,
                "model": model_id,
                "kb_snapshot_id": kb_snapshot_id,
            }
            | (audit_extra or {}),
        ),
    )
    outbox_id = await enqueue(
        conn,
        "runs",
        Message.create(
            "run.requested",
            ctx,
            {
                "run_id": str(rid),
                "variant": variant,
                "runtime": runtime,
                "model_id": model_id,
                "object_keys": list(keys),
                "requirements": requirements,
                "kb_snapshot_id": kb_snapshot_id,
            },
        ),
    )
    return run, outbox_id


async def create_run(
    deps: RunDeps,
    ctx: TenantContext,
    body: RunCreate,
    *,
    idempotency_key: str | None,
    route: str,
) -> Run:
    runtime = resolve_runtime(body.variant, body.runtime)
    check_model_allowed(deps, body.model_id)
    payload = body.model_dump(mode="json")
    async with tenant_transaction(deps.engine) as conn:
        stored = await idempotency.replay(conn, idempotency_key, payload, route=route)
        if stored is not None:
            return Run(**stored)
        run, outbox_id = await start_run(
            deps,
            ctx,
            conn,
            project_id=body.project_id,
            variant=body.variant,
            runtime=runtime,
            model_id=body.model_id,
            requirements=payload["requirements"],
        )
        await idempotency.store(
            conn, idempotency_key, payload, 202, run.model_dump(mode="json"), route=route
        )
    await deliver_now(deps.engine, deps.queues, ctx.tenant_id, outbox_id)
    return run


async def rerun(
    deps: RunDeps,
    ctx: TenantContext,
    run_id: uuid.UUID,
    *,
    idempotency_key: str | None,
    route: str,
) -> Run:
    """Starts a new run with the variant, runtime, model and requirements of ``run_id`` on
    the project's current parsed files (the run's own file snapshot is not kept) and a fresh
    knowledge-base snapshot (the same id as the original's when the KB is unchanged; ARCH-06).
    The model must still be allowed and the usual run quota applies."""
    payload = {"rerun_of": str(run_id)}
    async with tenant_transaction(deps.engine) as conn:
        stored = await idempotency.replay(conn, idempotency_key, payload, route=route)
        if stored is not None:
            return Run(**stored)
        row = await repo.get_for_rerun(conn, run_id)
        if row is None:
            raise _run_not_found()
        check_model_allowed(deps, row.model_id)
        run, outbox_id = await start_run(
            deps,
            ctx,
            conn,
            project_id=row.project_id,
            variant=row.variant,
            runtime=row.runtime,
            model_id=row.model_id,
            requirements=Requirements.model_validate(row.requirements).model_dump(mode="json"),
            audit_extra={"rerun_of": str(run_id)},
        )
        await idempotency.store(
            conn, idempotency_key, payload, 202, run.model_dump(mode="json"), route=route
        )
    await deliver_now(deps.engine, deps.queues, ctx.tenant_id, outbox_id)
    return run


async def cancel_run(engine: AsyncEngine, run_id: uuid.UUID) -> Run:
    """Marks the run ``failed`` with the error ``cancelled by user`` (the run status set has no
    separate value). A queued run is never started; a running run finishes its current step in
    the worker and the result is discarded (the worker only writes into a still-running row)."""
    async with tenant_transaction(engine) as conn:
        row = await repo.lock_status(conn, run_id)
        if row is None:
            raise _run_not_found()
        if row.status not in ("queued", "running"):
            raise ProblemError(
                409,
                "Conflict",
                f"a {row.status} run cannot be cancelled",
                slug="run-not-cancellable",
            )
        await repo.mark_failed(conn, run_id, CANCELLED)
        run = Run(**await get_run(conn, run_id))
        await emit_audit(
            conn,
            AuditEvent(
                action="run.cancelled",
                object_type="run",
                object_id=str(run_id),
                before={"status": row.status},
                after={"status": "failed", "error": CANCELLED},
            ),
        )
    return run


async def list_runs(
    engine: AsyncEngine, *, cursor: str | None, limit: int, project_id: uuid.UUID | None
) -> Page[Run]:
    after = page_filter(cursor, runs_table.c.created_at, runs_table.c.id)
    async with tenant_transaction(engine) as conn:
        rows = await repo.list_page(
            conn, after=after, project_id=project_id, limit=clamp(limit) + 1
        )
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[Run](items=[Run(**r) for r in rows], next_cursor=nxt)


async def read_run(engine: AsyncEngine, run_id: uuid.UUID) -> Run:
    async with tenant_transaction(engine) as conn:
        return Run(**await get_run(conn, run_id))


async def ensure_run_visible(engine: AsyncEngine, run_id: uuid.UUID) -> None:
    """404 unless the run exists in the caller's tenant."""
    async with tenant_transaction(engine) as conn:
        await get_run(conn, run_id)


async def progress(
    engine: AsyncEngine, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> tuple[str, dict[str, Any]]:
    """Status of the run and the progress snapshot streamed to clients (the agent worker
    appends every finished step to the trace)."""
    async with tenant_transaction(engine, tenant_id) as conn:
        row = await repo.progress_of(conn, run_id)
    snapshot = {
        "status": row.status,
        "usage": row.usage,
        "steps": len(row.trace),
        "step": row.trace[-1].get("node") if row.trace else None,
    }
    return str(row.status), snapshot


# ------------------------------------------------------------------------ BOM versions
async def latest_bom(conn: AsyncConnection, run_id: uuid.UUID) -> tuple[uuid.UUID, int, BomVersion]:
    row = await repo.latest_version(conn, run_id)
    if row is None:
        raise ProblemError(404, "Not Found", "no BOM for this run yet", slug="no-bom")
    return row.id, row.version, BomVersion.model_validate(row.content)


async def bom_at(conn: AsyncConnection, run_id: uuid.UUID, version: int) -> BomVersion:
    content = await repo.version_content(conn, run_id, version)
    if content is None:
        raise ProblemError(404, "Not Found", f"version {version} not found", slug="not-found")
    return BomVersion.model_validate(content)


async def read_bom(engine: AsyncEngine, run_id: uuid.UUID) -> tuple[int, BomVersion]:
    async with tenant_transaction(engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
    return version, bom


async def read_bom_version(engine: AsyncEngine, run_id: uuid.UUID, version: int) -> BomVersion:
    async with tenant_transaction(engine) as conn:
        return await bom_at(conn, run_id, version)


async def read_trace(engine: AsyncEngine, run_id: uuid.UUID) -> list[RunStep]:
    """Node name, duration and LLM calls per step; step details stay internal."""
    async with tenant_transaction(engine) as conn:
        row = await repo.trace_of(conn, run_id)
    if row is None:
        raise _run_not_found()
    return [
        RunStep(
            node=str(s.get("node", "")),
            duration_s=float(s.get("duration_s", 0.0)),
            llm_calls=int(s.get("llm_calls", 0)),
        )
        for s in row.trace or []
    ]


async def list_bom_versions(engine: AsyncEngine, run_id: uuid.UUID) -> list[BomVersionInfo]:
    """Newest first: the generated version 1 and every user correction after it."""
    async with tenant_transaction(engine) as conn:
        await get_run(conn, run_id)
        return [BomVersionInfo(**r) for r in await repo.version_history(conn, run_id)]


async def diff_bom_versions(
    engine: AsyncEngine, run_id: uuid.UUID, from_version: int, to_version: int
) -> BomDiffOut:
    async with tenant_transaction(engine) as conn:
        old = await bom_at(conn, run_id, from_version)
        new = await bom_at(conn, run_id, to_version)
    diff = diff_versions(old, new)
    return BomDiffOut(
        run_id=run_id,
        from_version=from_version,
        to_version=to_version,
        added=diff.added,
        removed=diff.removed,
        changed=[
            BomLineChange(
                line=c.line,
                refdes=c.refdes,
                fields=[BomFieldChange(**f.model_dump()) for f in c.fields],
            )
            for c in diff.changed
        ],
    )


async def evaluate_bom(engine: AsyncEngine, run_id: uuid.UUID, raw_reference: bytes) -> Evaluation:
    """Metrics of the thesis (line P/R/F1, designators, field accuracy, MPN coverage)
    against a reference BOM CSV the user uploads. Nothing is stored except an audit
    event; the CSV is parsed as plain text (no design-file parser runs in the API)."""
    try:
        ref_items = load_reference_csv(raw_reference.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, csv.Error) as exc:
        raise ProblemError(
            422,
            "Unprocessable Entity",
            "the reference must be a CSV BOM with a designator column (e.g. Reference)",
            slug="invalid-reference",
        ) from exc
    if not ref_items:
        raise ProblemError(
            422, "Unprocessable Entity", "the reference BOM has no lines", slug="invalid-reference"
        )
    async with tenant_transaction(engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
        report = evaluate(bom, ref_items, design=bom.design_name, variant=bom.variant)
        summary = {k: (None if math.isnan(v) else round(v, 6)) for k, v in report.summary().items()}
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.evaluated",
                object_type="run",
                object_id=str(run_id),
                after={
                    "version": version,
                    "reference_lines": len(ref_items),
                    "line_f1": summary.get("line_f1"),
                },
            ),
        )
    return Evaluation(
        run_id=run_id,
        version=version,
        reference_lines=len(ref_items),
        summary=summary,
        lines=Counts(**report.lines.model_dump()),
        designators=Counts(**report.designators.model_dump()),
        fields={k: FieldAccuracy(**v.model_dump()) for k, v in report.fields.items()},
        diffs=[ReferenceDiff(**d.model_dump()) for d in report.diffs],
    )


async def export_bom(
    engine: AsyncEngine, run_id: uuid.UUID, fmt: Literal["csv", "xlsx"], *, demo: bool
) -> ExportedBom:
    """Render the latest BOM as CSV or XLSX (carrying the run's KB snapshot id) and audit it."""
    async with tenant_transaction(engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
        snapshot = (await get_run(conn, run_id))["kb_snapshot_id"]
        after: dict[str, Any] = {"version": version}
        if fmt == "xlsx":
            after["format"] = "xlsx"
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.exported",
                object_type="run",
                object_id=str(run_id),
                after=after | {"kb_snapshot_id": snapshot},
            ),
        )
    content: str | bytes = (
        to_xlsx(bom, demo=demo, kb_snapshot_id=snapshot)
        if fmt == "xlsx"
        else to_csv(bom, demo=demo, kb_snapshot_id=snapshot)
    )
    return ExportedBom(version=version, kb_snapshot_id=snapshot, content=content)


async def patch_item(
    engine: AsyncEngine,
    kb: KnowledgeBase,
    ctx: TenantContext,
    run_id: uuid.UUID,
    line: int,
    body: BomItemPatch,
) -> tuple[int, BomVersion]:
    """Creates a new immutable BOM version with user provenance on the changed fields;
    a changed MPN is also stored as the organisation's knowledge (never global)."""
    changes = body.model_dump(exclude_none=True, exclude={"reason"})
    if not changes:
        raise ProblemError(422, "Unprocessable Entity", "nothing to change", slug="empty-patch")
    async with tenant_transaction(engine) as conn:
        # serialise edits of one run: concurrent PATCHes would race for the next version
        await repo.lock_run(conn, run_id)
        parent_id, version, bom = await latest_bom(conn, run_id)
        idx = next((n for n, i in enumerate(bom.items) if i.line == line), None)
        if idx is None:
            raise ProblemError(404, "Not Found", f"line {line} not found", slug="not-found")
        item = bom.items[idx]
        before = {k: getattr(item, k) for k in changes}
        prov = Provenance(kind=ProvenanceKind.USER, user_id=ctx.actor_id, rationale=body.reason)
        new_item = item.model_copy(
            update={**changes, "provenance": {**item.provenance, **dict.fromkeys(changes, prov)}}
        )
        items = list(bom.items)
        items[idx] = new_item
        new_bom = bom.model_copy(update={"items": items})
        await repo.insert_version(
            conn,
            run_id=run_id,
            version=version + 1,
            parent_id=parent_id,
            content_json=new_bom.model_dump_json(),
            reason=body.reason,
            created_by=ctx.actor_id,
        )
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.item_updated",
                object_type="bom_line",
                object_id=f"{run_id}:{line}",
                before=before,
                after=changes | {"reason": body.reason},
            ),
        )
        if changes.get("mpn"):
            await kb.add_correction(
                conn,
                mpn=changes["mpn"],
                manufacturer=changes.get("manufacturer", new_item.manufacturer),
                note=body.reason,
                attributes={"value": new_item.value, "footprint": new_item.footprint},
            )
    return version + 1, new_bom

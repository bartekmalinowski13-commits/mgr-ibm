"""REST API v1: a person reviews a run's BOM line by line.

The agents' BOM is never modified - it is the experiment's output (``?version=original``).
Each edit writes a reviewed copy with ``user`` provenance for the changed fields, re-runs
the deterministic rule pack, and records before/after in the audit log. Optionally the
correction becomes knowledge of this organisation only (ADR-0008: no cross-tenant
learning), via the kb-indexer.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response
from pydantic import Field, model_validator

from bomagent_api.auth import CAN_WRITE, require
from bomagent_api.routes import Ctx, Svc, _In, _source_ip, conflict, not_found
from bomagent_bom.model import BomVersion, Provenance, ProvenanceKind, Requirements
from bomagent_common import records
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import tenant_scope
from bomagent_rules import DEFAULT_PACK, validate

KB_CORRECTION = "kb.correction.requested"
_MPN = r"^[A-Za-z0-9][A-Za-z0-9.\-_/#+()]*$"
EDITABLE = ("mpn", "manufacturer", "dnp")

router = APIRouter(prefix="/v1", tags=["runs"])


class BomItemEdit(_In):
    mpn: str | None = Field(
        default=None, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9.\-_/#+()]*$"
    )
    manufacturer: str | None = Field(default=None, max_length=120)
    dnp: bool | None = None
    note: str = Field(min_length=1, max_length=500, description="Why - kept with the decision.")
    remember: bool = Field(
        default=False, description="Save the corrected part as this organisation's knowledge."
    )

    @model_validator(mode="after")
    def _something_changes(self) -> BomItemEdit:
        if all(getattr(self, f) is None for f in EDITABLE):
            raise ValueError("nothing to change: set mpn, manufacturer or dnp")
        if self.remember and not (self.mpn or self.manufacturer):
            raise ValueError("remember needs a part (mpn or manufacturer)")
        return self


def _revalidate(bom: BomVersion, line: int, requirements: Requirements) -> None:
    """Fresh findings from the deterministic pack; other packs' findings stay for untouched
    lines (they judged the old decision on the edited line)."""
    kept = [f for f in bom.findings if f.rule_pack != DEFAULT_PACK.id and f.line not in (line,)]
    bom.findings = kept + validate(bom.items, requirements).findings


@router.patch(
    "/runs/{run_id}/bom/items/{line}",
    responses={200: {"content": {"application/json": {}}, "description": "Reviewed BomVersion"}},
)
async def edit_bom_item(
    run_id: uuid.UUID,
    line: Annotated[int, Path(ge=1)],
    body: BomItemEdit,
    request: Request,
    ctx: Ctx,
    svc: Svc,
) -> Response:
    require(*CAN_WRITE)(ctx)
    if body.remember and svc.kb_queue is None:
        raise ProblemError(
            503, "Service Unavailable", "knowledge-base indexing is not configured", slug="kb-off"
        )
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        row = await records.get_run_for_update(conn, run_id)  # serialises concurrent edits
        if row is None:
            raise not_found("run")
        if row["status"] != "completed" or not row["bom_key"]:
            raise conflict("the BOM is not available yet")
        with tenant_scope(ctx):
            raw = await svc.store.get(row["reviewed_bom_key"] or row["bom_key"])
        bom = BomVersion.model_validate_json(raw)
        item = next((i for i in bom.items if i.line == line), None)
        if item is None:
            raise not_found("BOM line")

        changes = {f: getattr(body, f) for f in EDITABLE if getattr(body, f) is not None}
        before = {f: getattr(item, f) for f in changes}
        decided = Provenance(kind=ProvenanceKind.USER, user_id=ctx.actor_id, rationale=body.note)
        for field, value in changes.items():
            setattr(item, field, value)
            item.provenance[field] = decided
        _revalidate(bom, line, Requirements.model_validate(row["requirements"] or {}))

        reviewed_key = row["bom_key"].rsplit("/", 1)[0] + "/bom.reviewed.json"
        payload = bom.model_dump_json(indent=1).encode()
        with tenant_scope(ctx):
            await svc.store.put(reviewed_key, payload, "application/json")
        await records.mark_run_reviewed(conn, run_id, reviewed_key, ctx.actor_id)
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.item.edit",
                object_type="run",
                object_id=str(run_id),
                before={"line": line, **before},
                after={"line": line, **changes, "note": body.note, "remember": body.remember},
                source_ip=_source_ip(request),
            ),
            ctx,
        )
    if body.remember and svc.kb_queue is not None:
        await svc.kb_queue.send(
            Message.create(
                KB_CORRECTION,
                ctx,
                {"mpn": item.mpn, "manufacturer": item.manufacturer, "note": body.note},
            )
        )
    return Response(content=payload, media_type="application/json")

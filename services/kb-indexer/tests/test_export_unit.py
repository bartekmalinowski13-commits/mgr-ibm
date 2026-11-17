"""Organisation export: pure parts (no database)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from bomagent_common.org_export import (
    ExportStatus,
    archive_key,
    read_status,
    status_key,
    write_status,
)
from bomagent_common.storage import InMemoryObjectStore, InvalidObjectKeyError
from bomagent_kb_indexer.export import dumps, render_bom


def test_keys_live_under_the_tenant_prefix():
    tenant, job = uuid.uuid4(), uuid.uuid4()
    assert status_key(tenant, job) == f"tenants/{tenant}/exports/{job}/status.json"
    assert archive_key(tenant, job).startswith(f"tenants/{tenant}/exports/")


async def test_status_round_trip_and_unknown_job():
    store = InMemoryObjectStore(enforce_tenant=False)
    tenant, job = uuid.uuid4(), uuid.uuid4()
    assert await read_status(store, tenant, job) is None
    status = ExportStatus(
        id=job, status="queued", requested_by="u1", requested_at=datetime.now(UTC)
    )
    await write_status(store, tenant, status)
    assert await read_status(store, tenant, job) == status
    # another tenant's id resolves to a different key: nothing there
    assert await read_status(store, uuid.uuid4(), job) is None


async def test_tenant_enforcing_store_refuses_a_foreign_prefix():
    from bomagent_common.tenancy import TenantContext, tenant_scope

    store = InMemoryObjectStore()
    mine, other, job = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with (
        tenant_scope(TenantContext(tenant_id=mine, actor_id="u")),
        pytest.raises(InvalidObjectKeyError),
    ):
        await store.get(status_key(other, job))


def test_render_bom_keeps_json_when_csv_is_impossible():
    as_json, as_csv = render_bom({"not": "a bom"})
    assert json.loads(as_json) == {"not": "a bom"}
    assert as_csv is None


def test_dumps_handles_uuid_and_datetime():
    out = json.loads(dumps({"id": uuid.UUID(int=1), "at": datetime(2026, 1, 1, tzinfo=UTC)}))
    assert out["id"] == str(uuid.UUID(int=1))
    assert out["at"].startswith("2026-01-01")

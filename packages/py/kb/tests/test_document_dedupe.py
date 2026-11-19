"""Registering the same content twice at the same time yields one document, no error."""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from bomagent_common.db import tenant_transaction
from bomagent_common.tenancy import tenant_scope
from bomagent_kb import DocumentMeta, Scope

pytestmark = pytest.mark.integration


async def test_concurrent_identical_registrations_yield_one_document(app_engine, make_tenant, kb):
    tenant = await make_tenant()
    data = b"same content uploaded twice at once"
    meta = DocumentMeta(
        title="dup.md",
        mime_type="text/markdown",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    first_inserted = asyncio.Event()

    async def register(wait: bool) -> tuple[object, bool]:
        with tenant_scope(tenant):
            async with tenant_transaction(app_engine) as conn:
                if wait:  # the second one starts while the first is still uncommitted
                    await first_inserted.wait()
                result = await kb.register_document(
                    conn, meta, scope=Scope.TENANT, created_by=tenant.actor_id
                )
                if not wait:
                    first_inserted.set()
                    await asyncio.sleep(0.2)
                return result

    (id_a, created_a), (id_b, created_b) = await asyncio.gather(register(False), register(True))
    assert id_a == id_b
    assert sorted([created_a, created_b]) == [False, True]

    with tenant_scope(tenant):
        async with tenant_transaction(app_engine) as conn:
            assert (
                await kb.add_document(conn, meta, scope=Scope.TENANT, created_by=tenant.actor_id)
                == id_a
            )

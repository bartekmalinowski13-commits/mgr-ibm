from __future__ import annotations

import uuid

import boto3
import pytest
from moto import mock_aws

from bomagent_common.storage import (
    InMemoryObjectStore,
    InvalidObjectKeyError,
    S3ObjectStore,
    key_belongs_to,
    tenant_key,
)
from bomagent_common.tenancy import MissingTenantContextError, TenantContext, tenant_scope


def test_tenant_key_is_prefixed():
    tid = uuid.uuid4()
    key = tenant_key(tid, "projects", "p1", "board.kicad_sch")
    assert key == f"tenants/{tid}/projects/p1/board.kicad_sch"
    assert key_belongs_to(tid, key)
    assert not key_belongs_to(uuid.uuid4(), key)


@pytest.mark.parametrize("bad", ["..", ".", "", "a/b", "x\\y", "a b"])
def test_tenant_key_rejects_traversal(bad):
    with pytest.raises(InvalidObjectKeyError):
        tenant_key(uuid.uuid4(), "projects", bad)


async def test_in_memory_store_roundtrip():
    store = InMemoryObjectStore(enforce_tenant=False)
    await store.put("k", b"data")
    assert await store.get("k") == b"data"
    with pytest.raises(FileNotFoundError):
        await store.get("missing")
    assert (await store.presign_put("k")).startswith("memory://put/k")
    assert (await store.presign_get("k")).startswith("memory://get/k")


async def test_tenant_store_refuses_other_tenant_keys():
    store = InMemoryObjectStore()
    me, other = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(TenantContext(tenant_id=me, actor_id="u")):
        await store.put(tenant_key(me, "a.txt"), b"x")
        for op in (store.get, store.presign_get, store.presign_put):
            with pytest.raises(InvalidObjectKeyError):
                await op(tenant_key(other, "a.txt"))
        with pytest.raises(InvalidObjectKeyError):
            await store.put(tenant_key(other, "a.txt"), b"x")
    with pytest.raises(MissingTenantContextError):
        await store.get(tenant_key(me, "a.txt"))


async def test_s3_store_with_moto(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto3.client("s3", region_name="eu-central-1").create_bucket(
            Bucket="bomagent-test", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
        )
        store = S3ObjectStore("bomagent-test", region="eu-central-1")
        tid = uuid.uuid4()
        key = tenant_key(tid, "f.txt")
        with tenant_scope(TenantContext(tenant_id=tid, actor_id="u")):
            await store.put(key, b"hello", "text/plain")
            assert await store.get(key) == b"hello"
            assert "X-Amz-Signature" in await store.presign_get(key)
            assert "X-Amz-Signature" in await store.presign_put(key)
            with pytest.raises(InvalidObjectKeyError):
                await store.get(tenant_key(uuid.uuid4(), "f.txt"))

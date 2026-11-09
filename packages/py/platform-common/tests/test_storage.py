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
    store = InMemoryObjectStore()
    await store.put("k", b"data")
    assert await store.get("k") == b"data"
    with pytest.raises(FileNotFoundError):
        await store.get("missing")
    assert (await store.presign_put("k")).startswith("memory://put/k")
    assert (await store.presign_get("k")).startswith("memory://get/k")


async def test_s3_store_with_moto(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto3.client("s3", region_name="eu-central-1").create_bucket(
            Bucket="bomagent-test", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
        )
        store = S3ObjectStore("bomagent-test", region="eu-central-1")
        key = tenant_key(uuid.uuid4(), "f.txt")
        await store.put(key, b"hello", "text/plain")
        assert await store.get(key) == b"hello"
        assert "X-Amz-Signature" in await store.presign_get(key)
        assert "X-Amz-Signature" in await store.presign_put(key)

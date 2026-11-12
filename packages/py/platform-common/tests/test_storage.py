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


SUPABASE_S3 = "https://abcdefghijklmnop.supabase.co/storage/v1/s3"


class _Raw:
    """Minimal urllib3-like body for a stubbed botocore response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, *_: object, **__: object):
        yield self._body

    def read(self, amt: int | None = None) -> bytes:
        body, self._body = self._body, b""
        return body


def _stub_http(store: S3ObjectStore, sent: list) -> None:
    """Answer every S3 request locally (no network) and record what would be sent."""
    from botocore.awsrequest import AWSResponse

    def respond(request, **_: object) -> AWSResponse:
        sent.append(request)
        body = b"stored" if request.method == "GET" else b""
        status = 204 if request.method == "DELETE" else 200
        return AWSResponse(request.url, status, {}, _Raw(body))

    store._s3.meta.events.register("before-send.s3", respond)


def _supabase_settings(**kw):
    from bomagent_common.config import ServiceSettings

    return ServiceSettings(
        s3_endpoint_url=SUPABASE_S3, s3_region="eu-central-1", s3_force_path_style=True, **kw
    )


async def test_s3_compatible_endpoint_uses_path_style_and_its_region(monkeypatch):
    from bomagent_common.storage import make_object_store

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "supabase-s3-access-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "supabase-s3-secret")
    store = make_object_store(_supabase_settings(aws_region="us-east-1"), "bomagent-files")
    assert isinstance(store, S3ObjectStore)
    sent: list = []
    _stub_http(store, sent)
    tid = uuid.uuid4()
    key = tenant_key(tid, "f.txt")
    with tenant_scope(TenantContext(tenant_id=tid, actor_id="u")):
        await store.put(key, b"hello", "text/plain")
        assert await store.get(key) == b"stored"
        await store.delete(key)
        presigned = await store.presign_get(key)
    expected = f"{SUPABASE_S3}/bomagent-files/{key}"
    assert [r.method for r in sent] == ["PUT", "GET", "DELETE"]
    assert all(r.url.split("?")[0] == expected for r in sent)
    auth = sent[0].headers["Authorization"].decode()
    # SigV4 with the Supabase S3 access key and the project's region (not aws_region)
    assert "Credential=supabase-s3-access-key-id/" in auth
    assert "/eu-central-1/s3/aws4_request" in auth
    assert presigned.startswith(expected + "?")
    assert "eu-central-1" in presigned


async def test_s3_compatible_endpoint_skips_optional_checksums(monkeypatch):
    """S3-compatible stores do not all accept the CRC checksums boto3 adds by default."""
    from bomagent_common.storage import make_object_store

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    store = make_object_store(_supabase_settings(), "b", enforce_tenant=False)
    sent: list = []
    _stub_http(store, sent)
    await store.put("tenants/x/a", b"x")
    assert not any(h.lower().startswith("x-amz-checksum") for h in sent[0].headers)


def test_default_store_settings_keep_aws_behaviour():
    from bomagent_common.config import ServiceSettings
    from bomagent_common.storage import make_object_store

    settings = ServiceSettings()
    assert settings.s3_endpoint_url is None
    assert settings.s3_force_path_style is False
    store = make_object_store(settings, "bomagent-files")
    assert isinstance(store, S3ObjectStore)
    assert store._s3.meta.region_name == "eu-central-1"
    assert store._s3.meta.config.s3 in (None, {}) or (
        store._s3.meta.config.s3.get("addressing_style") in (None, "auto")
    )
    assert store._s3.meta.endpoint_url == "https://s3.eu-central-1.amazonaws.com"


def test_aws_endpoint_url_still_applies_to_s3_when_no_s3_endpoint_is_set():
    from bomagent_common.config import ServiceSettings
    from bomagent_common.storage import make_object_store

    store = make_object_store(ServiceSettings(aws_endpoint_url="http://moto:5000"), "b")
    assert store._s3.meta.endpoint_url == "http://moto:5000"

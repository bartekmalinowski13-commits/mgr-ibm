"""Object storage with mandatory per-tenant prefixes (``tenants/{tenant_id}/...``).

Keys are always derived from the tenant id - callers cannot address another tenant's
prefix, and path traversal segments are rejected. In AWS the task roles reach only the
``tenants/`` prefix of the files bucket; per-tenant prefixes are enforced here and by RLS
on the file metadata (per-tenant ABAC session policies are a planned hardening, see
DECISIONS_LOG).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import TYPE_CHECKING, Protocol

from bomagent_common.tenancy import require_tenant

if TYPE_CHECKING:
    from bomagent_common.config import ServiceSettings

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._\-]+$")


class InvalidObjectKeyError(ValueError):
    pass


def tenant_key(tenant_id: uuid.UUID, *parts: str) -> str:
    for p in parts:
        if not p or p in {".", ".."} or not _SAFE_SEGMENT.fullmatch(p):
            raise InvalidObjectKeyError(f"unsafe key segment: {p!r}")
    return "/".join(("tenants", str(tenant_id), *parts))


def key_belongs_to(tenant_id: uuid.UUID, key: str) -> bool:
    return key.startswith(f"tenants/{tenant_id}/") and ".." not in key.split("/")


def _check(key: str, enforce_tenant: bool) -> None:
    """Tenant-scoped stores only touch keys under the *active* tenant's prefix."""
    if enforce_tenant and not key_belongs_to(require_tenant().tenant_id, key):
        raise InvalidObjectKeyError("key outside the active tenant's prefix")


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str = ...) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def presign_put(self, key: str, expires: int = ...) -> str: ...
    async def presign_get(self, key: str, expires: int = ...) -> str: ...


class InMemoryObjectStore:
    def __init__(self, *, enforce_tenant: bool = True) -> None:
        self.objects: dict[str, bytes] = {}
        self._enforce = enforce_tenant

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        _check(key, self._enforce)
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        _check(key, self._enforce)
        try:
            return self.objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    async def delete(self, key: str) -> None:
        _check(key, self._enforce)
        self.objects.pop(key, None)

    async def presign_put(self, key: str, expires: int = 900) -> str:
        _check(key, self._enforce)
        return f"memory://put/{key}?expires={expires}"

    async def presign_get(self, key: str, expires: int = 900) -> str:
        _check(key, self._enforce)
        return f"memory://get/{key}?expires={expires}"


class S3ObjectStore:
    """S3 with SSE-KMS (bucket default encryption; enforced in CDK), or an S3-compatible
    store (Supabase Storage) at ``endpoint_url`` with ``force_path_style``.

    ``s3_compatible`` sends checksums only where the API requires them: boto3 adds CRC
    checksums to every upload by default, which not every S3-compatible service accepts.
    """

    def __init__(
        self,
        bucket: str,
        *,
        region: str,
        endpoint_url: str | None = None,
        enforce_tenant: bool = True,
        force_path_style: bool = False,
        s3_compatible: bool = False,
    ) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = bucket
        self._enforce = enforce_tenant
        options: dict[str, object] = {"signature_version": "s3v4"}
        if force_path_style:
            options["s3"] = {"addressing_style": "path"}
        if s3_compatible:
            options["request_checksum_calculation"] = "when_required"
            options["response_checksum_validation"] = "when_required"
        self._s3 = boto3.client(
            "s3", region_name=region, endpoint_url=endpoint_url, config=Config(**options)
        )

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        _check(key, self._enforce)
        await asyncio.to_thread(
            self._s3.put_object, Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        _check(key, self._enforce)
        resp = await asyncio.to_thread(self._s3.get_object, Bucket=self._bucket, Key=key)
        body: bytes = resp["Body"].read()
        return body

    async def delete(self, key: str) -> None:
        _check(key, self._enforce)
        await asyncio.to_thread(self._s3.delete_object, Bucket=self._bucket, Key=key)

    async def presign_put(self, key: str, expires: int = 900) -> str:
        _check(key, self._enforce)
        url: str = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url

    async def presign_get(self, key: str, expires: int = 900) -> str:
        _check(key, self._enforce)
        url: str = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url


def make_object_store(
    settings: ServiceSettings, bucket: str, *, enforce_tenant: bool = True
) -> S3ObjectStore:
    """S3 store from settings: AWS S3 by default, an S3-compatible endpoint (Supabase
    Storage) when ``s3_endpoint_url`` is set."""
    return S3ObjectStore(
        bucket,
        region=settings.s3_region or settings.aws_region,
        endpoint_url=settings.s3_endpoint_url or settings.aws_endpoint_url,
        enforce_tenant=enforce_tenant,
        force_path_style=settings.s3_force_path_style,
        s3_compatible=settings.s3_endpoint_url is not None,
    )

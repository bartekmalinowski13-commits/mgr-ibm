"""Object storage with mandatory per-tenant prefixes (``tenants/{tenant_id}/...``).

Keys are always derived from the tenant id - callers cannot address another tenant's
prefix, and path traversal segments are rejected. In AWS the task role is additionally
restricted to the prefix with session tags (ABAC), so a bug here is not enough to leak.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Protocol

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


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str = ...) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def presign_put(self, key: str, expires: int = ...) -> str: ...
    async def presign_get(self, key: str, expires: int = ...) -> str: ...


class InMemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    async def presign_put(self, key: str, expires: int = 900) -> str:
        return f"memory://put/{key}?expires={expires}"

    async def presign_get(self, key: str, expires: int = 900) -> str:
        return f"memory://get/{key}?expires={expires}"


class S3ObjectStore:
    """S3 with SSE-KMS (bucket default encryption; enforced in CDK)."""

    def __init__(self, bucket: str, *, region: str, endpoint_url: str | None = None) -> None:
        import boto3

        self._bucket = bucket
        self._s3 = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        await asyncio.to_thread(
            self._s3.put_object, Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        resp = await asyncio.to_thread(self._s3.get_object, Bucket=self._bucket, Key=key)
        body: bytes = resp["Body"].read()
        return body

    async def presign_put(self, key: str, expires: int = 900) -> str:
        url: str = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url

    async def presign_get(self, key: str, expires: int = 900) -> str:
        url: str = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url

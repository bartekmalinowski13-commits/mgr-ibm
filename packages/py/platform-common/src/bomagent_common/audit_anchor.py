"""Daily export of each tenant's audit chain head to write-once storage (ADR-0011, SEC-04).

The hash chain detects edits made without re-hashing; someone with table-owner rights could
re-hash the rest of the chain. The head ``(seq, hash)`` is therefore copied once a day to
storage the database owner cannot rewrite (S3 Object Lock in AWS; on the pilot a bucket with a
write-once policy and a second copy off-platform) and ``verify_chain(anchors=...)`` compares
the chain against them.

Objects are ``audit-anchors/<tenant>/<YYYY-MM-DD>.json`` = ``{tenant, seq, hash, at}``. Sinks
never overwrite: a second write of the same key returns ``False``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from bomagent_common.audit import ChainAnchor, chain_head
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

log = get_logger(__name__)
PREFIX = "audit-anchors/"
#: anchors compared on verification (about 13 months of daily anchors)
MAX_ANCHORS = 400


class AnchorSink(Protocol):
    async def write_once(self, key: str, data: bytes) -> bool:
        """Create ``key``; ``False`` (and no change) when it already exists."""
        ...

    async def read(self, key: str) -> bytes: ...

    async def list(self, prefix: str) -> list[str]:
        """Keys under ``prefix``, oldest first (keys sort by date)."""
        ...


def anchor_key(tenant_id: uuid.UUID, at: datetime) -> str:
    return f"{PREFIX}{tenant_id}/{at:%Y-%m-%d}.json"


def parse_anchor(data: bytes, tenant_id: uuid.UUID) -> ChainAnchor | None:
    """The anchor in ``data`` if it is a well-formed document of this tenant, else ``None``."""
    try:
        doc = json.loads(data)
    except ValueError:
        return None
    if not isinstance(doc, dict) or doc.get("tenant") != str(tenant_id):
        return None
    seq, digest = doc.get("seq"), doc.get("hash")
    if not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(digest, str):
        return None
    return ChainAnchor(seq, digest)


async def load_anchors(
    sink: AnchorSink, tenant_id: uuid.UUID, limit: int = MAX_ANCHORS
) -> list[ChainAnchor]:
    keys = (await sink.list(f"{PREFIX}{tenant_id}/"))[-limit:]
    anchors = []
    for key in keys:
        anchor = parse_anchor(await sink.read(key), tenant_id)
        if anchor is not None:
            anchors.append(anchor)
    return anchors


async def export_anchor(
    engine: AsyncEngine, sink: AnchorSink, tenant_id: uuid.UUID, now: datetime | None = None
) -> bool:
    """Write today's anchor of the tenant; ``False`` if there is nothing to anchor or it exists."""
    now = now or datetime.now(UTC)
    async with tenant_transaction(engine, tenant_id) as conn:
        head = await chain_head(conn, tenant_id)
    if head is None:
        return False
    doc = {"tenant": str(tenant_id), "seq": head.seq, "hash": head.hash, "at": now.isoformat()}
    return await sink.write_once(anchor_key(tenant_id, now), json.dumps(doc).encode())


class FileAnchorSink:
    """A directory (a mounted write-once volume, or the off-platform copy)."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not key.startswith(PREFIX) or not path.is_relative_to(self._root) or ".." in key:
            raise ValueError(f"not an anchor key: {key!r}")
        return path

    async def write_once(self, key: str, data: bytes) -> bool:
        path = self._path(key)

        def write() -> bool:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("xb") as f:  # exclusive create: never overwrites
                    f.write(data)
            except FileExistsError:
                return False
            return True

        return await asyncio.to_thread(write)

    async def read(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def list(self, prefix: str) -> list[str]:
        base = self._path(prefix.rstrip("/") + "/x").parent

        def scan() -> list[str]:
            if not base.is_dir():
                return []
            return sorted(f"{prefix.rstrip('/')}/{p.name}" for p in base.iterdir() if p.is_file())

        return await asyncio.to_thread(scan)


class S3AnchorSink:
    """An S3 bucket with Object Lock (AWS) or any S3-compatible bucket with a write-once policy.

    ``write_once`` checks for the key first and then puts with ``If-None-Match: *`` where the
    service supports it; stores that reject the header get a plain put after the check.
    """

    def __init__(
        self,
        bucket: str,
        *,
        region: str,
        endpoint_url: str | None = None,
        s3_compatible: bool = False,
    ) -> None:
        import boto3
        from botocore.config import Config

        options: dict[str, Any] = {"signature_version": "s3v4"}
        if endpoint_url:
            options["s3"] = {"addressing_style": "path"}
        if s3_compatible:
            options["request_checksum_calculation"] = "when_required"
            options["response_checksum_validation"] = "when_required"
        self._bucket = bucket
        self._s3 = boto3.client(
            "s3", region_name=region, endpoint_url=endpoint_url, config=Config(**options)
        )

    async def write_once(self, key: str, data: bytes) -> bool:
        return await asyncio.to_thread(self._write_once, key, data)

    def _write_once(self, key: str, data: bytes) -> bool:
        from botocore.exceptions import ClientError, ParamValidationError

        _check(key)
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise
        else:
            return False  # already exists: never overwritten
        args: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": data,
            "ContentType": "application/json",
        }
        try:
            self._s3.put_object(**args, IfNoneMatch="*")
        except ParamValidationError:  # an old botocore without the parameter
            self._s3.put_object(**args)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code"))
            if code in {"PreconditionFailed", "412", "ConditionalRequestConflict"}:
                return False  # another replica wrote it between the check and the put
            if code not in {"NotImplemented", "501"}:
                raise
            self._s3.put_object(**args)
        return True

    async def read(self, key: str) -> bytes:
        _check(key)
        resp = await asyncio.to_thread(self._s3.get_object, Bucket=self._bucket, Key=key)
        body: bytes = await asyncio.to_thread(resp["Body"].read)
        return body

    async def list(self, prefix: str) -> list[str]:
        _check(prefix)

        def scan() -> list[str]:
            keys: list[str] = []
            for page in self._s3.get_paginator("list_objects_v2").paginate(
                Bucket=self._bucket, Prefix=prefix
            ):
                keys.extend(obj["Key"] for obj in page.get("Contents", []))
            return sorted(keys)

        return await asyncio.to_thread(scan)


def _check(key: str) -> None:
    if not key.startswith(PREFIX) or ".." in key:
        raise ValueError(f"not an anchor key: {key!r}")

"""Idempotency-Key for creating POSTs (ARCHITECTURE / ADR-0015).

Same key + same body -> the stored response is replayed; same key + different body ->
422. Keys are per tenant (RLS) and stored in the same transaction as the created row.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_common.problems import ProblemError


def request_hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


async def replay(conn: AsyncConnection, key: str | None, body: Any) -> dict[str, Any] | None:
    if key is None:
        return None
    if not 8 <= len(key) <= 255:
        raise ProblemError(
            400, "Bad Request", "Idempotency-Key must be 8-255 characters", slug="idempotency-key"
        )
    row = (
        await conn.execute(
            text(
                "SELECT request_hash, response FROM app.idempotency_keys"
                " WHERE tenant_id = app.current_tenant_id() AND key = :k"
            ),
            {"k": key},
        )
    ).first()
    if row is None:
        return None
    if row.request_hash != request_hash(body):
        raise ProblemError(
            422,
            "Unprocessable Entity",
            "Idempotency-Key reused with a different request",
            slug="idempotency-mismatch",
        )
    stored: dict[str, Any] = row.response
    return stored


async def store(
    conn: AsyncConnection, key: str | None, body: Any, status: int, response: dict[str, Any]
) -> None:
    if key is None:
        return
    await conn.execute(
        text(
            "INSERT INTO app.idempotency_keys (tenant_id, key, request_hash, status_code,"
            " response) VALUES (app.current_tenant_id(), :k, :h, :s, CAST(:r AS jsonb))"
        ),
        {"k": key, "h": request_hash(body), "s": status, "r": json.dumps(response, default=str)},
    )

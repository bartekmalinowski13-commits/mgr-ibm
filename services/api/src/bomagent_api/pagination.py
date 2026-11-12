"""Cursor pagination (keyset on ``created_at DESC, id DESC``); cursors are opaque."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from bomagent_common.problems import ProblemError

MAX_LIMIT = 100


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(row_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts, rid = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(ts), uuid.UUID(rid)
    except (ValueError, TypeError) as exc:
        raise ProblemError(400, "Bad Request", "invalid cursor", slug="invalid-cursor") from exc


def page_clause(cursor: str | None, params: dict[str, Any], alias: str = "") -> str:
    p = f"{alias}." if alias else ""
    decoded = decode_cursor(cursor)
    if decoded is None:
        return ""
    params["c_ts"], params["c_id"] = decoded
    return f" AND ({p}created_at, {p}id) < (:c_ts, :c_id)"


def clamp(limit: int) -> int:
    return max(1, min(MAX_LIMIT, limit))

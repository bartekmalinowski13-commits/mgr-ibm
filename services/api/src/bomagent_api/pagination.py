"""Cursor pagination (keyset on ``created_at DESC, id DESC``); cursors are opaque."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, tuple_

from bomagent_common.problems import ProblemError

MAX_LIMIT = 100
MAX_BIGINT = 2**63 - 1


def _invalid_cursor() -> ProblemError:
    return ProblemError(400, "Bad Request", "invalid cursor", slug="invalid-cursor")


def _encode(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _decode(cursor: str) -> Any:
    """The JSON value inside an opaque cursor; anything malformed is a 400 problem."""
    if not cursor.isascii():
        raise _invalid_cursor()
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError) as exc:  # binascii.Error and JSON errors are ValueErrors
        raise _invalid_cursor() from exc


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    return _encode([created_at.isoformat(), str(row_id)])


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        ts, rid = _decode(cursor)
        return datetime.fromisoformat(ts), uuid.UUID(rid)
    except (ValueError, TypeError) as exc:
        raise _invalid_cursor() from exc


def encode_key_cursor(created_at: datetime, key: str) -> str:
    """Keyset cursor on ``(created_at, key)`` for rows whose identity is not a UUID."""
    return _encode([created_at.isoformat(), key])


def decode_key_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        ts, key = _decode(cursor)
        created_at = datetime.fromisoformat(ts)
    except (ValueError, TypeError) as exc:
        raise _invalid_cursor() from exc
    if not isinstance(key, str):
        raise _invalid_cursor()
    return created_at, key


def encode_seq_cursor(seq: int) -> str:
    """Opaque cursor on a sequence number (the audit log orders on ``seq``)."""
    return _encode({"seq": seq})


def decode_seq_cursor(cursor: str | None) -> int | None:
    if not cursor:
        return None
    decoded = _decode(cursor)
    seq = decoded.get("seq") if isinstance(decoded, dict) else None
    if type(seq) is not int or not 0 <= seq <= MAX_BIGINT:
        raise _invalid_cursor()
    return seq


def page_clause(cursor: str | None, params: dict[str, Any], alias: str = "") -> str:
    p = f"{alias}." if alias else ""
    decoded = decode_cursor(cursor)
    if decoded is None:
        return ""
    params["c_ts"], params["c_id"] = decoded
    return f" AND ({p}created_at, {p}id) < (:c_ts, :c_id)"


def clamp(limit: int) -> int:
    return max(1, min(MAX_LIMIT, limit))


def page_filter(
    cursor: str | None, created_at: ColumnElement[Any], row_id: ColumnElement[Any]
) -> ColumnElement[bool] | None:
    """Core counterpart of ``page_clause``: the keyset predicate for ``cursor`` (or None)."""
    decoded = decode_cursor(cursor)
    if decoded is None:
        return None
    return tuple_(created_at, row_id) < tuple_(*decoded)

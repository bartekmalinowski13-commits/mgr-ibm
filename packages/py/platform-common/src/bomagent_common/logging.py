"""Structured JSON logging (structlog) with redaction.

Rules (SECURITY.md): no customer file contents, prompts or secrets in application logs.
The redaction processor drops content-like keys and masks credential-like keys, so a
careless ``log.info("x", prompt=...)`` cannot leak data.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace

from bomagent_common.tenancy import current_tenant

DROPPED_KEYS = frozenset(
    {"content", "file_content", "file_bytes", "prompt", "messages", "completion", "text", "body"}
)
MASKED_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "authorization",
        "api_key",
        "apikey",
        "x-api-key",
        "cookie",
        "set-cookie",
        "dsn",
        "database_url",
        "private_key",
    }
)
MASKED_SUFFIXES = ("_token", "_secret", "_password", "_key", "-key", "_dsn", "_url_with_password")
MASK = "***"


def redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor removing sensitive values (recursively for nested dicts)."""

    def _value(v: Any) -> Any:
        if isinstance(v, dict):
            return _clean(dict(v))
        if isinstance(v, list | tuple):
            return type(v)(_value(x) for x in v)
        return v

    def _clean(d: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        for key in list(d.keys()):
            lk = str(key).lower()
            if lk in DROPPED_KEYS:
                d[key] = "[redacted]"
            elif lk in MASKED_KEYS or lk.endswith(MASKED_SUFFIXES):
                d[key] = MASK
            else:
                d[key] = _value(d[key])
        return d

    return _clean(event_dict)


def add_context(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Attach trace/span ids and tenant id for log ↔ trace correlation."""
    span_ctx = trace.get_current_span().get_span_context()
    if span_ctx.is_valid:
        event_dict.setdefault("trace_id", format(span_ctx.trace_id, "032x"))
        event_dict.setdefault("span_id", format(span_ctx.span_id, "016x"))
    tenant = current_tenant()
    if tenant is not None:
        event_dict.setdefault("tenant_id", str(tenant.tenant_id))
    return event_dict


def configure_logging(service_name: str, *, level: str = "INFO", json: bool = True) -> None:
    """Configure structlog + stdlib logging once per process."""
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_context,
        redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),  # resolves sys.stdout per call
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.bind_contextvars(service=service_name)
    logging.basicConfig(level=level, stream=sys.stdout, format="%(message)s")


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)

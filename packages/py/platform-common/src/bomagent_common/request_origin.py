"""The address a request came from, available to audit emission (audit SEC-04).

The API sets it once per request (from the trusted edge header, see ``bomagent_api.ip_limits``)
and :func:`bomagent_common.audit.emit_audit` records it in ``audit.events.source_ip``, so no
handler has to pass it around. Only a single valid IP address is ever stored: the column is
``inet`` and a bad value would fail the audit insert, and with it the request.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_source_ip: ContextVar[str | None] = ContextVar("source_ip", default=None)


def parse_ip(value: str | None) -> str | None:
    """The normalised address if ``value`` is exactly one IP address, else ``None``."""
    if not value or len(value) > 64:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def current_source_ip() -> str | None:
    return _source_ip.get()


@contextmanager
def source_ip_scope(value: str | None) -> Iterator[None]:
    token = _source_ip.set(parse_ip(value))
    try:
        yield
    finally:
        _source_ip.reset(token)

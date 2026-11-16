"""The caller's address reaches audit events without every handler passing it (SEC-04)."""

from __future__ import annotations

import pytest

from bomagent_common.request_origin import (
    current_source_ip,
    parse_ip,
    source_ip_scope,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.9", "203.0.113.9"),
        (" 203.0.113.9 ", "203.0.113.9"),
        ("2001:db8::1", "2001:db8::1"),
        ("::ffff:203.0.113.9", "::ffff:203.0.113.9"),
        ("unknown", None),
        ("", None),
        (None, None),
        ("1.2.3.4, 5.6.7.8", None),  # a list is not an address
        ("999.1.1.1", None),
        ("203.0.113.9/24", None),
        ("x" * 500, None),
    ],
)
def test_parse_ip_accepts_only_a_single_valid_address(raw, expected):
    assert parse_ip(raw) == expected


def test_scope_sets_and_restores_the_address():
    assert current_source_ip() is None
    with source_ip_scope("203.0.113.9"):
        assert current_source_ip() == "203.0.113.9"
        with source_ip_scope("198.51.100.1"):
            assert current_source_ip() == "198.51.100.1"
        assert current_source_ip() == "203.0.113.9"
    assert current_source_ip() is None


def test_scope_ignores_invalid_values():
    with source_ip_scope("not-an-ip"):
        assert current_source_ip() is None


async def test_scope_is_isolated_between_concurrent_tasks():
    import asyncio

    seen: dict[str, str | None] = {}

    async def request(name: str, ip: str, delay: float) -> None:
        with source_ip_scope(ip):
            await asyncio.sleep(delay)
            seen[name] = current_source_ip()

    await asyncio.gather(request("a", "203.0.113.1", 0.02), request("b", "203.0.113.2", 0.0))
    assert seen == {"a": "203.0.113.1", "b": "203.0.113.2"}

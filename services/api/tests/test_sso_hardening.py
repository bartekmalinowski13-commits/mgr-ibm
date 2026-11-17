"""SEC-05 SSO hardening that needs no database: provider names, free-mail blocklist, broker
error redaction, ``auth_time`` age check, discovery input."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from bomagent_api import sso
from bomagent_api.auth import TokenVerifier, _auth_time
from bomagent_api.schemas import SsoDiscoveryIn
from bomagent_api.sso import (
    is_free_mail,
    new_provider_name,
    require_sso_if_enforced,
    safe_error,
)
from bomagent_common.problems import ProblemError


# --------------------------------------------------------------------------- provider names
def test_provider_names_are_random_and_fit_cognito():
    names = {new_provider_name() for _ in range(200)}
    assert len(names) == 200
    for n in names:
        assert re.fullmatch(r"org-[0-9a-f]{24}", n)
        assert len(n) <= 32  # Cognito limit


# --------------------------------------------------------------------------- free mail
@pytest.mark.parametrize(
    "domain",
    ["gmail.com", "GMAIL.COM", "gmail.com.", "mail.gmail.com", "wp.pl", "outlook.com", "o2.pl"],
)
def test_free_mail_domains_are_refused(domain):
    assert is_free_mail(domain)


@pytest.mark.parametrize(
    "domain", ["clinic.example", "notgmail.com", "gmail.com.evil.example", "medtech.eu", "wp.pl.eu"]
)
def test_company_domains_are_allowed(domain):
    assert not is_free_mail(domain)


# --------------------------------------------------------------------------- error text
class BrokerError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": "InvalidParameterException"}}


def test_safe_error_hides_secret_and_infrastructure_identifiers():
    exc = BrokerError(
        "client secret s3cr3t-value rejected for arn:aws:cognito-idp:eu-central-1:123456789012:"
        "userpool/eu-central-1_AbC123xyz (pool eu-central-1_AbC123xyz, account 123456789012,"
        " client 3n4b5c6d7e8f9g0h1i2j3k4l5m)"
    )
    out = safe_error(exc, "s3cr3t-value")
    assert out.startswith("InvalidParameterException: ")
    for leaked in (
        "s3cr3t-value",
        "arn:aws",
        "123456789012",
        "AbC123xyz",
        "3n4b5c6d7e8f9g0h1i2j3k4l5m",
    ):
        assert leaked not in out
    assert "client secret *** rejected" in out


def test_safe_error_keeps_the_useful_part_and_is_bounded():
    out = safe_error(RuntimeError("metadata could not be fetched"), None)
    assert out == "RuntimeError: metadata could not be fetched"
    assert len(safe_error(RuntimeError("x" * 5000), None)) == 500


# --------------------------------------------------------------------------- discovery input
def test_discovery_takes_a_domain_only():
    assert SsoDiscoveryIn(domain=" Clinic.Example. ").domain == "clinic.example"
    for bad in ("ann@clinic.example", "clinic", "clinic.example/path", "a b.example", "", None, 5):
        with pytest.raises(ValidationError):
            SsoDiscoveryIn(domain=bad)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        SsoDiscoveryIn.model_validate({"domain": "clinic.example", "email": "a@clinic.example"})


async def test_discovery_never_looks_up_free_mail_or_empty_domains():
    class Boom:
        def begin(self) -> Any:  # a database call would fail the test
            raise AssertionError("no lookup expected")

    assert await sso.discover(Boom(), "gmail.com") is None  # type: ignore[arg-type]
    assert await sso.discover(Boom(), "") is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- auth_time claim
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1700000000, 1700000000),
        (1700000000.9, 1700000000),
        (True, None),
        ("1700000000", None),
        (-5, None),
        (None, None),
        ([1], None),
        ({"a": 1}, None),
    ],
)
def test_auth_time_claim_shapes(value, expected):
    assert _auth_time(value) == expected


def test_verifier_reads_auth_time_from_the_signed_token():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    v = TokenVerifier("https://idp", "aud", public_key=key.public_key())
    now = int(time.time())

    def tok(**c: Any) -> str:
        base = {"iss": "https://idp", "aud": "aud", "sub": "u", "exp": now + 60}
        return jwt.encode(base | c, key, algorithm="RS256")

    assert v.verify(tok(auth_time=now - 10)).auth_time == now - 10
    assert v.verify(tok()).auth_time is None
    assert v.verify(tok(auth_time="yesterday")).auth_time is None


# --------------------------------------------------------------------------- age check
class FakeConn:
    def __init__(self, stored_email: str, provider: str | None) -> None:
        self.stored_email, self.provider = stored_email, provider

    async def scalar(self, *_: Any, **__: Any) -> str:
        return self.stored_email

    async def execute(self, *_: Any, **__: Any) -> Any:
        provider = self.provider

        class Result:
            def first(self) -> Any:
                return None if provider is None else type("Row", (), {"provider_name": provider})()

        return Result()


@pytest.fixture
def enforced(monkeypatch):
    def install(provider: str | None = "org-abc") -> None:
        class Tx:
            def __init__(self, engine: Any, tenant_id: Any = None) -> None: ...

            async def __aenter__(self) -> FakeConn:
                return FakeConn("vera@clinic.example", provider)

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        monkeypatch.setattr(sso, "tenant_transaction", Tx)

    return install


async def check(
    provider: str | None, auth_time: int | None, max_age: int, roles: tuple[str, ...] = ("viewer",)
) -> None:
    await require_sso_if_enforced(
        None,  # type: ignore[arg-type]
        uuid.uuid4(),
        "u",
        "vera@clinic.example",
        provider,
        list(roles),
        auth_time=auth_time,
        max_auth_age_s=max_age,
    )


async def test_recent_sign_in_passes_and_old_or_missing_is_reauth(enforced):
    enforced()
    now = int(time.time())
    await check("org-abc", now - 60, 8 * 3600)
    for stale in (now - 8 * 3600 - 60, None):
        with pytest.raises(ProblemError) as err:
            await check("org-abc", stale, 8 * 3600)
        assert err.value.problem.status == 401
        assert err.value.problem.type.endswith("/reauth-required")


async def test_age_check_can_be_switched_off_and_owners_are_exempt(enforced):
    enforced()
    await check("org-abc", None, 0)
    await check("org-abc", 1, 0)
    await check("org-abc", None, 3600, roles=("owner",))


async def test_wrong_provider_is_still_sso_required_and_unenforced_is_untouched(enforced):
    enforced()
    with pytest.raises(ProblemError) as err:
        await check(None, int(time.time()), 3600)
    assert err.value.problem.status == 403
    assert err.value.problem.type.endswith("/sso-required")
    enforced(provider=None)  # no enforced connection for the domain
    await check(None, None, 3600)

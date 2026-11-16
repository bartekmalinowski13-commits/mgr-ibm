"""All-in-one process (Supabase pilot): API + workers on the PostgreSQL queue + the SPA."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_allinone.app import QUEUES, Settings, _llm, create_app, spa_csp
from bomagent_common.messaging import PostgresQueue
from bomagent_common.storage import InMemoryObjectStore
from bomagent_llm.chat import FakeChat, GatewayChat
from bomagent_testing.data import FIXTURES, KICAD_FIXTURES

REF = "abcdefghijklmnop"
SUPABASE_URL = f"https://{REF}.supabase.co"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>BOM Agent</title>")
    (tmp_path / "assets" / "app-1a2b3c.js").write_text("console.log('spa')")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    return tmp_path


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"environment": "test", "auth_mode": "local"}
    return Settings(**(base | kw))


# ---------------------------------------------------------------- settings


def test_defaults_target_supabase():
    s = Settings(environment="test", supabase_url=SUPABASE_URL, supabase_anon_key="anon")
    assert s.queue_backend == "postgres"
    assert s.oidc_issuer == f"{SUPABASE_URL}/auth/v1"
    assert s.oidc_jwks_url == f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    assert s.oidc_audience == "authenticated"
    assert s.oidc_algorithms == ["ES256", "RS256"]
    assert s.oidc_email_verified_claim == "user_metadata.email_verified"
    assert s.oidc_name_claims == ["user_metadata.full_name", "user_metadata.name"]
    assert s.llm_gateway_url is None  # the deterministic fake provider by default


def test_explicit_issuer_wins_and_trailing_slash_is_ignored():
    s = Settings(
        environment="test",
        supabase_url=SUPABASE_URL + "/",
        oidc_issuer="https://issuer.example/auth/v1",
        oidc_jwks_url="https://issuer.example/jwks",
    )
    assert s.oidc_issuer == "https://issuer.example/auth/v1"
    assert s.oidc_jwks_url == "https://issuer.example/jwks"
    assert s.supabase_url == SUPABASE_URL


def test_supabase_also_confirms_e_mails_through_its_user_endpoint():
    s = Settings(environment="test", supabase_url=SUPABASE_URL, supabase_anon_key="anon")
    assert s.oidc_userinfo_url == f"{SUPABASE_URL}/auth/v1/user"
    assert s.oidc_userinfo_apikey == "anon"


@pytest.mark.parametrize(
    "field",
    ["supabase_url", "llm_gateway_url", "s3_endpoint_url", "oidc_jwks_url", "oidc_userinfo_url"],
)
def test_outside_local_and_test_endpoints_must_use_https(field):
    """No plain-HTTP JWKS (forged keys) and no unencrypted data leaving the host
    (security review L3)."""
    base = {"supabase_url": SUPABASE_URL, "supabase_anon_key": "anon"}
    with pytest.raises(ValidationError, match="https"):
        Settings(environment="dev", **(base | {field: "http://example.eu/x"}))
    Settings(environment="test", **(base | {field: "http://localhost:9/x"}))


PILOT = {"environment": "dev", "supabase_url": SUPABASE_URL, "supabase_anon_key": "anon"}


def test_fake_llm_is_allowed_by_default_only_in_local_and_test():
    assert Settings(environment="test").allow_fake_llm is True
    assert Settings(environment="local").allow_fake_llm is True
    assert Settings(**PILOT).allow_fake_llm is False
    assert Settings(**PILOT, allow_fake_llm=True).allow_fake_llm is True
    assert Settings(environment="test", allow_fake_llm=False).allow_fake_llm is False


def test_allow_fake_llm_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("BOMAGENT_ALLOW_FAKE_LLM", "true")
    assert Settings(**PILOT).allow_fake_llm is True


def test_llm_fails_closed_without_a_gateway_unless_the_fake_is_allowed():
    with pytest.raises(RuntimeError, match="BOMAGENT_LLM_GATEWAY_URL"):
        _llm(Settings(**PILOT))
    chat, _ = _llm(Settings(**PILOT, allow_fake_llm=True))
    assert isinstance(chat, FakeChat)
    chat, _ = _llm(Settings(environment="test"))
    assert isinstance(chat, FakeChat)


def test_a_half_configured_gateway_is_an_error_even_when_the_fake_is_allowed():
    with pytest.raises(RuntimeError, match="both"):
        _llm(Settings(**PILOT, allow_fake_llm=True, llm_gateway_url="https://g.example.eu"))
    with pytest.raises(RuntimeError, match="both"):
        _llm(Settings(**PILOT, allow_fake_llm=True, llm_gateway_key="k"))


def test_the_gateway_is_used_when_configured():
    settings = Settings(
        **PILOT, llm_gateway_url="http://mgr-ibm-llm-gateway.internal:4000", llm_gateway_key="k"
    )
    chat, _ = _llm(settings)
    assert isinstance(chat, GatewayChat)


@pytest.mark.parametrize(
    "url",
    [
        "http://mgr-ibm-llm-gateway.internal:4000",
        "http://mgr-ibm-llm-gateway.internal",
        "https://gateway.example.eu",
    ],
)
def test_gateway_may_use_http_only_on_the_private_network(url):
    Settings(**PILOT, llm_gateway_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://gateway.example.eu",
        "http://internal.example.com",
        "http://evil.internal.example.com:4000",
        "http://localhost:4000",
        "http://10.0.0.1:4000",
        "http://x.internal@evil.example.com",
    ],
)
def test_gateway_http_elsewhere_is_refused(url):
    with pytest.raises(ValidationError, match="https"):
        Settings(**PILOT, llm_gateway_url=url)


def test_only_the_postgres_queue_is_supported():
    with pytest.raises(ValidationError, match="postgres"):
        Settings(environment="test", queue_backend="sqs")


def test_needs_both_database_roles():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(_settings())


def test_csp_allows_the_supabase_origin_only_for_connections():
    csp = spa_csp(SUPABASE_URL + "/")
    assert "default-src 'self'" in csp
    assert f"connect-src 'self' {SUPABASE_URL}" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self';" in csp
    assert "unsafe-eval" not in csp
    assert spa_csp(None).count("connect-src 'self';") == 1


@pytest.mark.integration
@pytest.mark.parametrize("gateway", [False, True])
async def test_fake_provider_models_are_selectable_only_without_a_gateway(
    app_engine, platform_engine, gateway
):
    extra = {"llm_gateway_url": "https://gateway.example.eu", "llm_gateway_key": "k"}
    app = create_app(
        Settings(
            environment="dev",
            supabase_url=SUPABASE_URL,
            supabase_anon_key="anon",
            start_workers=False,
            allow_fake_llm=True,
            **(extra if gateway else {}),
        ),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    assert app.state.allow_local_models is (not gateway)
    kind = "gateway" if gateway else "fake"
    assert app.state.readyz_info == {"llm": kind, "embeddings": kind}
    assert app.state.demo is (not gateway)


# ---------------------------------------------------------------- HTTP surface


@contextlib.asynccontextmanager
async def running(app) -> AsyncIterator[httpx.AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://pilot") as c,
    ):
        yield c


@pytest.mark.integration
async def test_config_json_for_supabase_auth(app_engine, platform_engine):
    app = create_app(
        _settings(
            auth_mode="oidc",
            supabase_url=SUPABASE_URL,
            supabase_anon_key="public-anon-key",
            start_workers=False,
        ),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        resp = await client.get("/config.json")
    assert resp.status_code == 200
    assert resp.json() == {
        "auth": {"mode": "supabase", "url": SUPABASE_URL, "anonKey": "public-anon-key"},
        "mode": "demo",
        "llm": "fake",
        "embeddings": "fake",
    }
    assert resp.headers["cache-control"] == "no-store"


def test_client_ip_header_defaults_to_fly_only_on_fly(monkeypatch):
    # behind Fly's proxy the socket peer is the proxy: without the edge header every user
    # would share one per-IP bucket
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    assert Settings(environment="test").client_ip_header is None
    monkeypatch.setenv("FLY_APP_NAME", "mgr-ibm")
    assert Settings(environment="test").client_ip_header == "Fly-Client-IP"
    assert (
        Settings(environment="test", client_ip_header="X-Edge-IP").client_ip_header == "X-Edge-IP"
    )


def test_social_providers_are_parsed_from_a_comma_separated_value():
    assert Settings(environment="test").social_provider_ids == []
    s = Settings(environment="test", social_providers=" Google, azure ,apple,google,facebook,, ")
    assert s.social_provider_ids == ["google", "azure", "apple"]


@pytest.mark.integration
async def test_config_json_lists_enabled_social_providers(app_engine, platform_engine):
    app = create_app(
        _settings(
            auth_mode="oidc",
            supabase_url=SUPABASE_URL,
            supabase_anon_key="public-anon-key",
            social_providers="google,azure",
            start_workers=False,
        ),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        resp = await client.get("/config.json")
    assert resp.json()["auth"]["providers"] == ["google", "azure"]


@pytest.mark.integration
async def test_config_json_in_local_mode_and_without_supabase(app_engine, platform_engine):
    app = create_app(
        _settings(start_workers=False),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        assert (await client.get("/config.json")).json() == {
            "auth": {"mode": "local"},
            "mode": "demo",
            "llm": "fake",
            "embeddings": "fake",
        }
    app = create_app(
        _settings(auth_mode="oidc", start_workers=False),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        assert (await client.get("/config.json")).status_code == 404


@pytest.mark.integration
async def test_spa_is_served_with_fallback(app_engine, platform_engine, static_dir):
    app = create_app(
        _settings(static_dir=str(static_dir), start_workers=False, supabase_url=SUPABASE_URL),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        index = await client.get("/")
        deep = await client.get("/projects/123/runs")
        asset = await client.get("/assets/app-1a2b3c.js")
        missing_asset = await client.get("/assets/missing.js")
        traversal = await client.get("/assets/..%2F..%2Fetc%2Fpasswd")
        api_404 = await client.get("/v1/does-not-exist")
        health = await client.get("/healthz")
        openapi = await client.get("/openapi.json")
    assert index.status_code == 200
    assert "BOM Agent" in index.text
    assert index.headers["cache-control"] == "no-cache"
    assert index.headers["content-security-policy"] == spa_csp(SUPABASE_URL)
    assert index.headers["x-frame-options"] == "DENY"
    assert deep.status_code == 200
    assert deep.text == index.text
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert missing_asset.status_code == 404
    assert traversal.status_code == 404 or traversal.text == index.text
    assert "root:" not in traversal.text
    assert api_404.status_code == 404
    assert api_404.headers["content-type"].startswith("application/problem+json")
    assert health.json()["status"] == "ok"
    assert "/v1/projects" in openapi.json()["paths"]
    assert not any(p.startswith("/{") for p in openapi.json()["paths"])


# ---------------------------------------------------------------- end to end


async def _wait_for(check, timeout_s: float = 90.0) -> Any:
    deadline = time.monotonic() + timeout_s
    while True:
        value = await check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.2)


@pytest.mark.integration
async def test_upload_and_variant_b_run_complete_in_one_process(
    app_engine, platform_engine, static_dir
):
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    app = create_app(
        _settings(
            static_dir=str(static_dir),
            queue_poll_interval_s=0.05,
            queue_wait_seconds=1,
            maintenance_interval_s=0.5,
        ),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
        retriever_factory=lambda tenant, snapshot: retriever,
    )
    queues = app.state.queues
    assert {type(q) for q in queues.values()} == {PostgresQueue}
    s = uuid.uuid4().hex[:6]
    async with running(app) as c:
        ready = await c.get("/readyz")
        assert ready.status_code == 200, ready.text
        assert ready.json()["checks"] == {"database": True, "workers": True}

        token = await c.post("/v1/dev/token", json={"sub": f"pilot-{s}", "email": f"p-{s}@x.eu"})
        auth = {"Authorization": f"Bearer {token.json()['access_token']}"}
        org = await c.post(
            "/v1/organizations", headers=auth, json={"name": f"pilot-{s}", "slug": f"pilot-{s}"}
        )
        assert org.status_code == 201, org.text
        auth["X-Org-Id"] = org.json()["id"]
        pid = (await c.post("/v1/projects", headers=auth, json={"name": "ECG"})).json()["id"]
        for path in sorted((KICAD_FIXTURES / "ecg-frontend").glob("*.kicad_*")):
            resp = await c.post(
                f"/v1/projects/{pid}/files",
                headers=auth,
                files={"file": (path.name, path.read_bytes())},
            )
            assert resp.status_code == 201, resp.text

        async def parsed() -> list[dict[str, Any]] | None:
            # every upload re-parses the whole project; the last ingest sees all sheets
            files = (await c.get(f"/v1/projects/{pid}/files", headers=auth)).json()
            done = {f["status"] for f in files} == {"parsed"}
            return files if done and files[0]["summary"]["components"] == 30 else None

        await _wait_for(parsed)

        run = await c.post("/v1/runs", headers=auth, json={"project_id": pid, "variant": "B"})
        assert run.status_code == 202, run.text
        run_id = run.json()["id"]

        async def finished() -> dict[str, Any] | None:
            body = (await c.get(f"/v1/runs/{run_id}", headers=auth)).json()
            return body if body["status"] in {"completed", "failed"} else None

        done = await _wait_for(finished)
        assert done["status"] == "completed", done
        bom = (await c.get(f"/v1/runs/{run_id}/bom", headers=auth)).json()
        assert bom["version"] == 1
        assert bom["bom"]["items"]


# ---------------------------------------------------------------- entrypoint


def test_entrypoint_dispatches_commands(monkeypatch):
    import sys

    import uvicorn

    import bomagent_migrations
    from bomagent_allinone.__main__ import main

    seen: list[object] = []
    monkeypatch.setattr(sys, "argv", list(sys.argv))  # main() rewrites it for the CLI
    monkeypatch.setattr(bomagent_migrations, "main", lambda: seen.append(list(sys.argv)))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.append((app, kw["factory"])))
    main(["migrate"])
    main(["bootstrap"])
    main([])
    assert seen == [
        ["bomagent-migrate", "upgrade"],
        ["bomagent-migrate", "bootstrap"],
        ("bomagent_allinone.app:create_app", True),
    ]
    with pytest.raises(SystemExit, match="usage"):
        main(["deploy"])


# ---------------------------------------------------------------- process roles (ARCH-02)


def test_role_decides_what_a_process_runs():
    assert Settings(environment="test").role == "all"  # default: the pilot as it is today
    all_ = Settings(environment="test", role="all")
    web = Settings(environment="test", role="web")
    worker = Settings(environment="test", role="worker")
    assert (all_.runs_workers, all_.serves_web) == (True, True)
    assert (web.runs_workers, web.serves_web) == (False, True)
    assert (worker.runs_workers, worker.serves_web) == (True, False)
    # start_workers=False (tests, local tools) still wins over the role
    assert not Settings(environment="test", role="worker", start_workers=False).runs_workers


def test_the_outbox_relay_and_reaper_belong_to_the_web_process():
    from bomagent_allinone.app import effective_settings

    worker = Settings(environment="test", role="worker", maintenance_interval_s=30)
    assert effective_settings(worker).maintenance_interval_s == 0
    for role in ("all", "web"):
        s = Settings(environment="test", role=role, maintenance_interval_s=30)
        assert effective_settings(s).maintenance_interval_s == 30
    assert worker.maintenance_interval_s == 30  # the original is untouched


def test_roles_report_under_their_own_service_name():
    from bomagent_allinone.app import effective_settings

    names = {
        role: effective_settings(Settings(environment="test", role=role)).service_name
        for role in ("all", "web", "worker")
    }
    assert names == {
        "all": "bomagent-allinone",
        "web": "bomagent-allinone-web",
        "worker": "bomagent-allinone-worker",
    }


def test_an_unknown_role_is_refused():
    with pytest.raises(ValueError, match="role"):
        Settings(environment="test", role="everything")


@pytest.mark.integration
async def test_web_role_serves_the_api_and_runs_no_consumers(app_engine, platform_engine):
    app = create_app(
        _settings(role="web", queue_wait_seconds=1),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        assert app.state.workers.tasks == []
        ready = (await client.get("/readyz")).json()
        assert "workers" not in ready["checks"]  # nothing to wait for in a web process
        assert (await client.get("/config.json")).status_code == 200


@pytest.mark.integration
async def test_worker_role_runs_consumers_serves_no_frontend_and_no_maintenance(
    app_engine, platform_engine
):
    app = create_app(
        _settings(role="worker", queue_wait_seconds=1, maintenance_interval_s=30),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        assert len(app.state.workers.tasks) == len(QUEUES) + 1  # consumers and the purge loop
        assert (await client.get("/config.json")).status_code == 404  # no SPA, no sign-in config
        ready = await client.get("/readyz")
        assert ready.json()["checks"]["workers"] is True


@pytest.mark.integration
@pytest.mark.parametrize(("role", "expected_sweeps"), [("worker", False), ("web", True)])
async def test_only_the_web_process_runs_the_maintenance_loop(
    app_engine, platform_engine, monkeypatch, role, expected_sweeps
):
    import asyncio

    from bomagent_api import maintenance

    calls: list[int] = []

    async def fake_sweep(*args, **kwargs):
        calls.append(1)
        return {"sent": 0, "reaped": 0, "purged": 0}

    monkeypatch.setattr(maintenance, "sweep", fake_sweep)
    app = create_app(
        _settings(role=role, queue_wait_seconds=1, maintenance_interval_s=0.05),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app):
        await asyncio.sleep(0.4)
    assert bool(calls) is expected_sweeps

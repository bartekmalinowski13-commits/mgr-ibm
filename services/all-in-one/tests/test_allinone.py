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
from bomagent_allinone.app import Settings, create_app, spa_csp
from bomagent_common.messaging import PostgresQueue
from bomagent_common.storage import InMemoryObjectStore
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
            **(extra if gateway else {}),
        ),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    assert app.state.allow_local_models is (not gateway)


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
        "auth": {"mode": "supabase", "url": SUPABASE_URL, "anonKey": "public-anon-key"}
    }
    assert resp.headers["cache-control"] == "no-store"


@pytest.mark.integration
async def test_config_json_in_local_mode_and_without_supabase(app_engine, platform_engine):
    app = create_app(
        _settings(start_workers=False),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(),
    )
    async with running(app) as client:
        assert (await client.get("/config.json")).json() == {"auth": {"mode": "local"}}
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

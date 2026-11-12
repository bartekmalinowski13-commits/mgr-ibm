"""Sample projects: the pack itself (no database) and its seeding into organisations."""

from __future__ import annotations

import csv
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from bomagent_api.app import Settings, create_app
from bomagent_api.samples import SAMPLE_PREFIX, SAMPLES, load_files
from bomagent_api.samples.catalog import DATA_DIR
from bomagent_bom.model import Requirements
from bomagent_cad import FileRef, parse_files
from bomagent_cli.main import deterministic_bom
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue, process_one
from bomagent_common.storage import InMemoryObjectStore
from bomagent_eval import evaluate, load_reference
from bomagent_ingest.handler import IngestWorker
from bomagent_testing.data import REPO_ROOT

ROOT = Path(__file__).resolve().parents[3]
assert REPO_ROOT == ROOT


# ---------------------------------------------------------------- the pack (no database)


def test_pack_has_five_distinct_designs_in_several_formats() -> None:
    assert len(SAMPLES) >= 5
    assert len({s.key for s in SAMPLES}) == len(SAMPLES)
    assert len({s.project_name for s in SAMPLES}) == len(SAMPLES)
    assert all(s.project_name.startswith(SAMPLE_PREFIX) for s in SAMPLES)
    formats = {
        parse_files([FileRef(n, d) for n, d in load_files(s)]).source_format for s in SAMPLES
    }
    assert sum(f.startswith("kicad") for f in formats) >= 3
    assert formats - {f for f in formats if f.startswith("kicad")}  # a non-KiCad format


def test_every_sample_is_complete_and_documented() -> None:
    for s in SAMPLES:
        assert (s.directory / "README.md").is_file(), s.key
        assert (s.directory / "reference_bom.csv").is_file(), s.key
        assert "CC0-1.0" in (s.directory / "README.md").read_text(), s.key
        assert s.files, s.key
        assert all((s.directory / f).is_file() for f in s.files), s.key
        on_disk = {
            p.name
            for p in s.directory.iterdir()
            if p.name not in {"README.md", "reference_bom.csv"}
        }
        assert on_disk == set(s.files), f"{s.key}: catalogue and folder disagree"


def test_evals_samples_points_at_the_pack() -> None:
    assert (ROOT / "evals" / "samples").resolve() == DATA_DIR.resolve()


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.key)
def test_every_sample_parses_and_matches_its_reference(sample) -> None:
    design = parse_files([FileRef(n, d) for n, d in load_files(sample)])
    assert design.components
    bom = deterministic_bom([FileRef(n, d) for n, d in load_files(sample)], Requirements())
    reference = load_reference(sample.directory / "reference_bom.csv")
    report = evaluate(bom, reference, design=sample.key)
    assert report.summary()["line_f1"] >= 0.9, report.summary()
    assert report.summary()["designator_f1"] >= 0.99
    rows = list(csv.DictReader((sample.directory / "reference_bom.csv").open()))
    assert rows
    # every line has an MPN except test points and DNP placeholders
    assert all(r["MPN"] or r["DNP"] or r["Value"] == "TestPoint" for r in rows)


# ---------------------------------------------------------------- seeding (PostgreSQL)

pg = pytest.mark.integration


class Env:
    def __init__(self, app_engine, platform_engine, **settings) -> None:
        self.store = InMemoryObjectStore(enforce_tenant=False)
        self.queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue()}
        self.engine = app_engine
        self.app = create_app(
            Settings(environment="test", auth_mode="local", **({"seed_samples": True} | settings)),
            engine=app_engine,
            platform_engine=platform_engine,
            store=self.store,
            queues=self.queues,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://api"
        )

    async def login(self, sub: str) -> dict[str, str]:
        resp = await self.client.post("/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    async def org(self, sub: str, slug: str) -> dict[str, str]:
        auth = await self.login(sub)
        resp = await self.client.post(
            "/v1/organizations", headers=auth, json={"name": slug, "slug": slug}
        )
        assert resp.status_code == 201, resp.text
        return auth | {"X-Org-Id": resp.json()["id"]}

    async def projects(self, headers: dict[str, str]) -> list[dict]:
        resp = await self.client.get("/v1/projects?limit=100", headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()["items"]

    async def drain_ingest(self) -> None:
        worker = IngestWorker(self.engine, self.store)
        queue = self.queues["ingest"]
        while items := await queue.receive(max_messages=10):
            for item in items:
                assert await process_one(queue, item, worker.handle)


@pytest.fixture
async def env(app_engine, platform_engine):
    return Env(app_engine, platform_engine)


def uniq() -> str:
    return uuid.uuid4().hex[:8]


@pg
async def test_new_organisation_gets_all_samples_labelled_and_parsed(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"seed-{s}")
    projects = await env.projects(owner)
    assert sorted(p["name"] for p in projects) == sorted(x.project_name for x in SAMPLES)
    assert all(p["is_sample"] for p in projects)

    await env.drain_ingest()
    for project in projects:
        files = (await env.client.get(f"/v1/projects/{project['id']}/files", headers=owner)).json()
        assert files, project["name"]
        assert {f["status"] for f in files} == {"parsed"}, project["name"]
        assert all(f["summary"]["components"] > 0 for f in files if f["detected_format"])


@pg
async def test_seeding_is_audited_and_keeps_the_hash_chain(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"audit-{s}")
    events = (await env.client.get("/v1/audit-events?limit=100", headers=owner)).json()["items"]
    seeded = [e for e in events if e["action"] == "org.samples_seeded"]
    assert len(seeded) == 1
    assert sorted(seeded[0]["after"]["added"]) == sorted(x.key for x in SAMPLES)
    assert sum(e["action"] == "project.created" for e in events) == len(SAMPLES)
    assert (await env.client.get("/v1/audit-events/verify", headers=owner)).json()["ok"] is True


@pg
async def test_readding_is_idempotent_and_restores_deleted_samples(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"idem-{s}")
    again = await env.client.post("/v1/samples", headers=owner)
    assert again.status_code == 200, again.text
    assert again.json() == {"added": [], "existing": sorted(x.key for x in SAMPLES)}
    assert len(await env.projects(owner)) == len(SAMPLES)
    events = (await env.client.get("/v1/audit-events?limit=100", headers=owner)).json()["items"]
    assert sum(e["action"] == "org.samples_seeded" for e in events) == 1  # nothing new, no event

    victim = next(p for p in await env.projects(owner) if p["name"].endswith("ECG patch"))
    deleted = await env.client.delete(f"/v1/projects/{victim['id']}", headers=owner)
    assert deleted.status_code == 204, deleted.text
    restored = await env.client.post("/v1/samples", headers=owner)
    assert restored.json()["added"] == ["ecg-patch"]
    assert len(await env.projects(owner)) == len(SAMPLES)


@pg
async def test_readding_is_safe_under_concurrency(env, app_engine) -> None:
    import asyncio

    s = uniq()
    owner = await env.org(f"own-{s}", f"race-{s}")
    victim = next(p for p in await env.projects(owner) if p["name"].endswith("Pulse oximeter"))
    await env.client.delete(f"/v1/projects/{victim['id']}", headers=owner)
    results = await asyncio.gather(
        *(env.client.post("/v1/samples", headers=owner) for _ in range(4))
    )
    assert all(r.status_code == 200 for r in results)
    assert sum(len(r.json()["added"]) for r in results) == 1
    assert len(await env.projects(owner)) == len(SAMPLES)


@pg
async def test_only_owners_can_readd_samples(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"roles-{s}")
    invite = await env.client.post(
        "/v1/invitations", headers=owner, json={"email": f"eng-{s}@x.eu", "roles": ["engineer"]}
    )
    assert invite.status_code == 201, invite.text
    member = await env.login(f"eng-{s}")
    accepted = await env.client.post(
        "/v1/invitations/accept", headers=member, json={"token": invite.json()["token"]}
    )
    assert accepted.status_code == 200, accepted.text
    engineer = member | {"X-Org-Id": owner["X-Org-Id"]}
    assert (await env.client.post("/v1/samples", headers=engineer)).status_code == 403
    outsider = await env.login(f"out-{s}")
    resp = await env.client.post("/v1/samples", headers=outsider | {"X-Org-Id": owner["X-Org-Id"]})
    assert resp.status_code in (403, 404)


@pg
async def test_seeding_never_touches_another_organisation(env, app_engine) -> None:
    s = uniq()
    a = await env.org(f"a-{s}", f"org-a-{s}")
    b = await env.org(f"b-{s}", f"org-b-{s}")
    # drop B's samples; adding A's again must not bring them back
    for p in await env.projects(b):
        assert (await env.client.delete(f"/v1/projects/{p['id']}", headers=b)).status_code == 204
    assert (await env.client.post("/v1/samples", headers=a)).json()["added"] == []
    assert await env.projects(b) == []
    # A's rows carry A's tenant id, B sees none of them, and A's objects sit under A's prefix
    async with tenant_transaction(app_engine, uuid.UUID(a["X-Org-Id"])) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT count(*) FILTER (WHERE tenant_id = app.current_tenant_id()),"
                    " count(*) FROM projects.projects"
                )
            )
        ).one()
        assert rows[0] == rows[1] == len(SAMPLES)
        keys = (await conn.execute(text("SELECT object_key FROM projects.files"))).scalars().all()
    assert keys
    assert all(k.startswith(f"tenants/{a['X-Org-Id']}/") for k in keys)
    async with tenant_transaction(app_engine, uuid.UUID(b["X-Org-Id"])) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM projects.files"))).scalar() == 0


@pg
async def test_samples_are_exempt_from_the_project_quota(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"quota-{s}")
    # pilot plan: 20 projects; the five samples do not count
    for i in range(20):
        resp = await env.client.post("/v1/projects", headers=owner, json={"name": f"mine {i}"})
        assert resp.status_code == 201, (i, resp.text)
    over = await env.client.post("/v1/projects", headers=owner, json={"name": "one too many"})
    assert over.status_code == 429


@pg
async def test_only_sample_projects_can_be_deleted(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"del-{s}")
    mine = (await env.client.post("/v1/projects", headers=owner, json={"name": "mine"})).json()
    refused = await env.client.delete(f"/v1/projects/{mine['id']}", headers=owner)
    assert refused.status_code == 409
    sample = next(p for p in await env.projects(owner) if p["is_sample"])
    keys_before = set(env.store.objects)
    assert (
        await env.client.delete(f"/v1/projects/{sample['id']}", headers=owner)
    ).status_code == 204
    assert len(set(env.store.objects)) < len(keys_before)  # type: ignore[attr-defined]
    assert (await env.client.get(f"/v1/projects/{sample['id']}", headers=owner)).status_code == 404
    events = (await env.client.get("/v1/audit-events?limit=100", headers=owner)).json()["items"]
    assert any(e["action"] == "project.deleted" for e in events)


@pg
async def test_users_cannot_fake_a_sample_project(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"fake-{s}")
    resp = await env.client.post(
        "/v1/projects", headers=owner, json={"name": f"{SAMPLE_PREFIX}mine", "is_sample": True}
    )
    assert resp.status_code == 422  # unknown field: samples come from the platform only


@pg
async def test_setting_off_disables_seeding_and_the_endpoint(app_engine, platform_engine) -> None:
    off = Env(app_engine, platform_engine, seed_samples=False)
    s = uniq()
    owner = await off.org(f"own-{s}", f"off-{s}")
    assert await off.projects(owner) == []
    assert (await off.client.post("/v1/samples", headers=owner)).status_code == 404
    events = (await off.client.get("/v1/audit-events?limit=100", headers=owner)).json()["items"]
    assert all(e["action"] != "org.samples_seeded" for e in events)


def test_default_setting_by_environment(monkeypatch) -> None:
    monkeypatch.delenv("BOMAGENT_SEED_SAMPLES", raising=False)

    def enabled(environment: str, **kw) -> bool:
        return Settings(
            environment=environment,
            auth_mode="local" if environment in {"local", "test"} else "oidc",
            **kw,
        ).samples_enabled

    assert enabled("local")
    assert enabled("test")
    assert Settings(environment="dev").samples_enabled
    assert not Settings(environment="staging").samples_enabled
    assert not Settings(environment="prod").samples_enabled
    assert Settings(environment="prod", seed_samples=True).samples_enabled
    assert not Settings(environment="dev", seed_samples=False).samples_enabled


# ---------------------------------------------------------------- review fixes


async def join(env: Env, owner: dict[str, str], sub: str, role: str) -> dict[str, str]:
    invite = await env.client.post(
        "/v1/invitations", headers=owner, json={"email": f"{sub}@x.eu", "roles": [role]}
    )
    assert invite.status_code == 201, invite.text
    user = await env.login(sub)
    ok = await env.client.post(
        "/v1/invitations/accept", headers=user, json={"token": invite.json()["token"]}
    )
    assert ok.status_code == 200, ok.text
    return user | {"X-Org-Id": owner["X-Org-Id"]}


async def first_sample(env: Env, owner: dict[str, str]) -> dict:
    return next(p for p in await env.projects(owner) if p["is_sample"])


@pg
async def test_sample_projects_refuse_uploads(env) -> None:
    owner = await env.org(f"own-{uniq()}", f"ro-{uniq()}")
    sample = await first_sample(env, owner)
    resp = await env.client.post(
        f"/v1/projects/{sample['id']}/files", headers=owner, files={"file": ("x.edf", b"x")}
    )
    assert resp.status_code == 409
    assert resp.json()["type"].endswith("sample-read-only")
    assert "sample" in resp.json()["detail"]


@pg
async def test_delete_needs_admin_and_is_tenant_scoped(env) -> None:
    s = uniq()
    owner = await env.org(f"own-{s}", f"dr-{s}")
    other = await env.org(f"oth-{s}", f"dr-o-{s}")
    sample = await first_sample(env, owner)
    url = f"/v1/projects/{sample['id']}"
    for role in ("viewer", "reviewer", "engineer"):
        member = await join(env, owner, f"{role}-{s}", role)
        assert (await env.client.delete(url, headers=member)).status_code == 403, role
    assert (await env.client.delete(url, headers=other)).status_code == 404
    assert (await env.client.get(url, headers=owner)).status_code == 200


@pg
async def test_delete_refused_while_a_run_is_active(env) -> None:
    owner = await env.org(f"own-{uniq()}", f"act-{uniq()}")
    sample = await first_sample(env, owner)
    await env.drain_ingest()
    run = await env.client.post(
        "/v1/runs", headers=owner, json={"project_id": sample["id"], "variant": "B"}
    )
    assert run.status_code == 202, run.text
    resp = await env.client.delete(f"/v1/projects/{sample['id']}", headers=owner)
    assert resp.status_code == 409
    assert "deleting" in resp.json()["detail"]


@pg
async def test_delete_audit_records_counts_and_stale_ingest_is_skipped(env) -> None:
    owner = await env.org(f"own-{uniq()}", f"aud-{uniq()}")
    sample = await first_sample(env, owner)
    files = (await env.client.get(f"/v1/projects/{sample['id']}/files", headers=owner)).json()
    # the ingest message of the project is still queued when the project is deleted
    deleted = await env.client.delete(f"/v1/projects/{sample['id']}", headers=owner)
    assert deleted.status_code == 204
    events = (await env.client.get("/v1/audit-events?limit=100", headers=owner)).json()["items"]
    event = next(e for e in events if e["action"] == "project.deleted")
    assert event["before"]["files"] == len(files)
    assert event["before"]["runs"] == 0
    assert event["before"]["bom_versions"] == 0
    # the worker acks the stale message and records no failure for the vanished project
    await env.drain_ingest()
    events = (await env.client.get("/v1/audit-events?limit=100", headers=owner)).json()["items"]
    stale = [
        e
        for e in events
        if e["action"].startswith("project.files_") and e["object_id"] == sample["id"]
    ]
    assert not stale


@pg
async def test_seeding_queues_one_ingest_message_per_project(env) -> None:
    await env.org(f"own-{uniq()}", f"msg-{uniq()}")
    received = await env.queues["ingest"].receive(max_messages=10)
    assert len(received) == len(SAMPLES)


@pg
async def test_seeding_is_metered_and_the_endpoint_is_rate_limited(env, app_engine) -> None:
    owner = await env.org(f"own-{uniq()}", f"rl-{uniq()}")
    async with tenant_transaction(app_engine, uuid.UUID(owner["X-Org-Id"])) as conn:
        uploaded = (
            await conn.execute(
                text("SELECT COALESCE(sum(files_uploaded), 0) FROM metering.usage_daily")
            )
        ).scalar()
    assert uploaded == sum(len(s.files) for s in SAMPLES)
    codes = [(await env.client.post("/v1/samples", headers=owner)).status_code for _ in range(8)]
    assert codes[0] == 200
    assert 429 in codes

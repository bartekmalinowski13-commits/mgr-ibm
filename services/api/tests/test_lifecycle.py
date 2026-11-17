"""Lifecycle actions (UX-03): rename/delete projects, delete files, cancel and re-run runs,
BOM version history + diff, XLSX export. Real PostgreSQL (CI), in-memory store and queues."""

from __future__ import annotations

import io
import uuid
import zipfile

import httpx
import pytest
from sqlalchemy import text

from bomagent_api.app import Settings, create_app
from bomagent_bom.model import BomItem, BomVersion
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.api import mark_files_parsed

pytestmark = pytest.mark.integration


class Env:
    def __init__(self, app_engine, platform_engine) -> None:
        self.store = InMemoryObjectStore(enforce_tenant=False)
        self.queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue()}
        self.engine = app_engine
        self.app = create_app(
            Settings(environment="test", auth_mode="local", seed_samples=False),
            engine=app_engine,
            platform_engine=platform_engine,
            store=self.store,
            queues=self.queues,
        )
        self.c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://api"
        )

    async def org(self, sub: str, slug: str) -> dict[str, str]:
        resp = await self.c.post("/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu"})
        auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        org = await self.c.post(
            "/v1/organizations", headers=auth, json={"name": slug, "slug": slug}
        )
        assert org.status_code == 201, org.text
        return auth | {"X-Org-Id": org.json()["id"]}

    async def project_with_file(self, h: dict[str, str]) -> tuple[str, dict]:
        pid = (await self.c.post("/v1/projects", headers=h, json={"name": "mine"})).json()["id"]
        up = await self.c.post(
            f"/v1/projects/{pid}/files", headers=h, files={"file": ("a.csv", b"Reference\nR1\n")}
        )
        assert up.status_code == 201, up.text
        await mark_files_parsed(self.engine, h["X-Org-Id"])
        return pid, up.json()

    async def run(self, h: dict[str, str], pid: str, **extra) -> dict:
        resp = await self.c.post(
            "/v1/runs", headers=h, json={"project_id": pid, "variant": "B"} | extra
        )
        assert resp.status_code == 202, resp.text
        return resp.json()

    async def set_status(self, h: dict[str, str], run_id: str, status: str) -> None:
        async with tenant_transaction(self.engine, uuid.UUID(h["X-Org-Id"])) as conn:
            await conn.execute(
                text("UPDATE runs.runs SET status = :s WHERE id = :i"), {"s": status, "i": run_id}
            )

    async def add_versions(self, h: dict[str, str], run_id: str) -> None:
        """Version 1 (generated) and version 2 (a correction), as the worker and PATCH write."""
        v1 = BomVersion(
            design_name="t", items=[BomItem(line=1, refdes=["R1"], quantity=1, mpn="OLD")]
        )
        v2 = v1.model_copy(
            update={"items": [BomItem(line=1, refdes=["R1"], quantity=1, mpn="NEW")]}
        )
        ids = [uuid.uuid4(), uuid.uuid4()]
        async with tenant_transaction(self.engine, uuid.UUID(h["X-Org-Id"])) as conn:
            for n, (vid, bom, parent) in enumerate([(ids[0], v1, None), (ids[1], v2, ids[0])], 1):
                await conn.execute(
                    text(
                        "INSERT INTO bom.versions (id, tenant_id, run_id, version, parent_id,"
                        " content, reason, created_by) VALUES (:i, app.current_tenant_id(), :r,"
                        " :v, :p, CAST(:c AS jsonb), :why, 'u')"
                    ),
                    {
                        "i": vid,
                        "r": run_id,
                        "v": n,
                        "p": parent,
                        "c": bom.model_dump_json(),
                        "why": "generated" if n == 1 else "fix mpn",
                    },
                )
            await conn.execute(
                text("UPDATE runs.runs SET status = 'completed' WHERE id = :i"), {"i": run_id}
            )

    async def actions(self, h: dict[str, str]) -> list[str]:
        resp = await self.c.get("/v1/audit-events?limit=100", headers=h)
        return [e["action"] for e in resp.json()["items"]]


@pytest.fixture
async def env(app_engine, platform_engine):
    return Env(app_engine, platform_engine)


def uniq() -> str:
    return uuid.uuid4().hex[:8]


async def test_rename_and_delete_own_project_removes_objects(env) -> None:
    s = uniq()
    h = await env.org(f"o-{s}", f"life-{s}")
    pid, _ = await env.project_with_file(h)
    renamed = await env.c.patch(
        f"/v1/projects/{pid}", headers=h, json={"name": "Renamed", "description": "d"}
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["description"]) == ("Renamed", "d")
    empty = await env.c.patch(f"/v1/projects/{pid}", headers=h, json={})
    assert empty.status_code == 422

    assert env.store.objects
    assert (await env.c.delete(f"/v1/projects/{pid}", headers=h)).status_code == 204
    assert not env.store.objects
    assert (await env.c.get(f"/v1/projects/{pid}", headers=h)).status_code == 404
    actions = await env.actions(h)
    assert "project.updated" in actions
    assert "project.deleted" in actions
    assert (await env.c.get("/v1/audit-events/verify", headers=h)).json()["ok"] is True


async def test_delete_file_removes_object_and_is_refused_while_a_run_is_active(env) -> None:
    s = uniq()
    h = await env.org(f"o-{s}", f"file-{s}")
    pid, info = await env.project_with_file(h)
    run = await env.run(h, pid)
    refused = await env.c.delete(f"/v1/projects/{pid}/files/{info['id']}", headers=h)
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("file-in-use")
    assert refused.headers["content-type"].startswith("application/problem+json")
    assert env.store.objects  # nothing was removed
    assert (await env.c.delete(f"/v1/projects/{pid}", headers=h)).status_code == 409

    await env.set_status(h, run["id"], "completed")
    ok = await env.c.delete(f"/v1/projects/{pid}/files/{info['id']}", headers=h)
    assert ok.status_code == 204, ok.text
    assert not env.store.objects
    assert (await env.c.get(f"/v1/projects/{pid}/files", headers=h)).json() == []
    again = await env.c.delete(f"/v1/projects/{pid}/files/{info['id']}", headers=h)
    assert again.status_code == 404
    assert "file.deleted" in await env.actions(h)


async def test_delete_never_touches_keys_outside_the_tenant_prefix(env) -> None:
    s = uniq()
    h = await env.org(f"o-{s}", f"prefix-{s}")
    pid, info = await env.project_with_file(h)
    foreign = "tenants/00000000-0000-0000-0000-000000000000/projects/x/y/a.csv"
    env.store.objects[foreign] = b"other tenant"
    async with tenant_transaction(env.engine, uuid.UUID(h["X-Org-Id"])) as conn:
        await conn.execute(
            text("UPDATE projects.files SET object_key = :k WHERE id = :i"),
            {"k": foreign, "i": info["id"]},
        )
    assert (
        await env.c.delete(f"/v1/projects/{pid}/files/{info['id']}", headers=h)
    ).status_code == 204
    assert foreign in env.store.objects


async def test_lifecycle_actions_are_tenant_scoped_and_role_checked(env) -> None:
    s = uniq()
    a = await env.org(f"a-{s}", f"la-{s}")
    b = await env.org(f"b-{s}", f"lb-{s}")
    pid, info = await env.project_with_file(a)
    run = await env.run(a, pid)
    assert (
        await env.c.patch(f"/v1/projects/{pid}", headers=b, json={"name": "x"})
    ).status_code == 404
    assert (
        await env.c.delete(f"/v1/projects/{pid}/files/{info['id']}", headers=b)
    ).status_code == 404
    assert (await env.c.post(f"/v1/runs/{run['id']}/cancel", headers=b)).status_code == 404
    assert (await env.c.post(f"/v1/runs/{run['id']}/rerun", headers=b)).status_code == 404
    assert (await env.c.get(f"/v1/runs/{run['id']}/bom/versions", headers=b)).status_code == 404


async def test_cancel_run(env) -> None:
    s = uniq()
    h = await env.org(f"o-{s}", f"cancel-{s}")
    pid, _ = await env.project_with_file(h)
    run = await env.run(h, pid)
    cancelled = await env.c.post(f"/v1/runs/{run['id']}/cancel", headers=h)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "failed"
    assert cancelled.json()["error"] == "cancelled by user"
    assert cancelled.json()["finished_at"]
    again = await env.c.post(f"/v1/runs/{run['id']}/cancel", headers=h)
    assert again.status_code == 409
    assert again.json()["type"].endswith("run-not-cancellable")
    assert "run.cancelled" in await env.actions(h)
    # the project is free again: its files can be deleted
    files = (await env.c.get(f"/v1/projects/{pid}/files", headers=h)).json()
    assert (
        await env.c.delete(f"/v1/projects/{pid}/files/{files[0]['id']}", headers=h)
    ).status_code == 204


async def test_rerun_uses_the_same_settings_and_is_idempotent(env) -> None:
    s = uniq()
    h = await env.org(f"o-{s}", f"rerun-{s}")
    pid, _ = await env.project_with_file(h)
    first = await env.run(h, pid)
    await env.set_status(h, first["id"], "completed")
    key = {"Idempotency-Key": f"rr-{s}"}
    again = await env.c.post(f"/v1/runs/{first['id']}/rerun", headers=h | key)
    assert again.status_code == 202, again.text
    new = again.json()
    assert new["id"] != first["id"]
    assert (new["variant"], new["runtime"], new["model_id"], new["status"]) == (
        first["variant"],
        first["runtime"],
        first["model_id"],
        "queued",
    )
    replay = await env.c.post(f"/v1/runs/{first['id']}/rerun", headers=h | key)
    assert replay.json()["id"] == new["id"]
    queued = await env.queues["runs"].receive(max_messages=10)
    assert any(m.message.payload["run_id"] == new["id"] for m in queued)
    # ARCH-06: an unchanged knowledge base is reused, so both runs share one snapshot
    assert first["kb_snapshot_id"]
    assert new["kb_snapshot_id"] == first["kb_snapshot_id"]
    assert any(
        m.message.payload["run_id"] == new["id"]
        and m.message.payload["kb_snapshot_id"] == new["kb_snapshot_id"]
        for m in queued
    )
    assert (await env.c.post(f"/v1/runs/{uuid.uuid4()}/rerun", headers=h)).status_code == 404


async def test_bom_versions_diff_and_xlsx(env) -> None:
    s = uniq()
    h = await env.org(f"o-{s}", f"ver-{s}")
    pid, _ = await env.project_with_file(h)
    run = await env.run(h, pid)
    await env.add_versions(h, run["id"])
    versions = (await env.c.get(f"/v1/runs/{run['id']}/bom/versions", headers=h)).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["parent_version"] == 1
    assert versions[1]["parent_version"] is None
    assert versions[0]["reason"] == "fix mpn"
    one = await env.c.get(f"/v1/runs/{run['id']}/bom/versions/1", headers=h)
    assert one.json()["bom"]["items"][0]["mpn"] == "OLD"
    assert (await env.c.get(f"/v1/runs/{run['id']}/bom/versions/9", headers=h)).status_code == 404
    diff = (
        await env.c.get(
            f"/v1/runs/{run['id']}/bom/diff", headers=h, params={"from_version": 1, "to_version": 2}
        )
    ).json()
    assert diff["added"] == []
    assert diff["removed"] == []
    assert diff["changed"][0]["fields"] == [{"field": "mpn", "before": "OLD", "after": "NEW"}]

    xlsx = await env.c.get(f"/v1/runs/{run['id']}/bom.xlsx", headers=h)
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith("application/vnd.openxmlformats")
    with zipfile.ZipFile(io.BytesIO(xlsx.content)) as zf:
        assert b"NEW" in zf.read("xl/worksheets/sheet1.xml")
    assert "bom.exported" in await env.actions(h)

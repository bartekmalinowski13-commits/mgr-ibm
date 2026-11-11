"""Demo data for the local devstack (`devstack.py --seed`), created through the public API.

Everything goes through the same HTTP endpoints the web app uses, so the demo exercises the
real tenant context, RLS and audit trail. Only open fixtures from `evals/fixtures/kicad`
are uploaded; the LLM is the deterministic fake provider (no keys, no network).

The demo user signs in in the web app with the e-mail below; the mock IdP derives the same
subject from the e-mail as this script, so the seeded organisation is already there.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
KICAD = ROOT / "evals/fixtures/kicad"

DEMO_EMAIL = "anna@medtech-demo.example"
DEMO_NAME = "Anna"
DEMO_ORG = ("MedTech Demo", "medtech-demo")
# (project name, fixture directory, variants to run)
DEMO_PROJECTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ECG front-end", "ecg-frontend", ("A", "B")),
    ("EEG 2-channel", "eeg-2ch", ("B",)),
    ("Pulse oximeter", "pulse-ox", ("B",)),
)


def dev_sub(email: str) -> str:
    """Same subject as the web app's `devSignIn` (apps/web/src/lib/session.tsx)."""
    return "dev-" + re.sub(r"[^a-z0-9]+", "-", email.lower())


@dataclass(frozen=True)
class SeedResult:
    org_id: str
    project_ids: tuple[str, ...]
    run_ids: tuple[str, ...]


async def _wait(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], done: object, timeout_s: float
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        if done(resp.json()):  # type: ignore[operator]
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"demo seed: {url} not ready after {timeout_s}s")


async def seed(client: httpx.AsyncClient, timeout_s: float = 120.0) -> SeedResult:
    """Create the demo organisation, projects, parsed files and completed runs."""
    token = await client.post(
        "/v1/dev/token",
        json={"sub": dev_sub(DEMO_EMAIL), "email": DEMO_EMAIL, "name": DEMO_NAME},
    )
    token.raise_for_status()
    auth = {"Authorization": f"Bearer {token.json()['access_token']}"}
    org = await client.post(
        "/v1/organizations", headers=auth, json={"name": DEMO_ORG[0], "slug": DEMO_ORG[1]}
    )
    org.raise_for_status()
    headers = auth | {"X-Org-Id": org.json()["id"]}

    project_ids: list[str] = []
    run_ids: list[str] = []
    for name, fixture, variants in DEMO_PROJECTS:
        project = await client.post(
            "/v1/projects",
            headers=headers | {"Idempotency-Key": f"demo-{fixture}"},
            json={"name": name},
        )
        project.raise_for_status()
        pid = project.json()["id"]
        project_ids.append(pid)
        paths = sorted((KICAD / fixture).glob("*.kicad_*"))
        for path in paths:
            resp = await client.post(
                f"/v1/projects/{pid}/files",
                headers=headers,
                files={"file": (path.name, path.read_bytes())},
            )
            resp.raise_for_status()
        expected = len(paths)

        def all_parsed(files: list[dict[str, str]], expected: int = expected) -> bool:
            return len(files) == expected and all(f["status"] == "parsed" for f in files)

        await _wait(client, f"/v1/projects/{pid}/files", headers, all_parsed, timeout_s)
        for variant in variants:
            run = await client.post(
                "/v1/runs", headers=headers, json={"project_id": pid, "variant": variant}
            )
            run.raise_for_status()
            run_ids.append(run.json()["id"])

    for run_id in run_ids:
        await _wait(
            client,
            f"/v1/runs/{run_id}",
            headers,
            lambda r: r["status"] in {"completed", "failed"},
            timeout_s,
        )
    return SeedResult(org.json()["id"], tuple(project_ids), tuple(run_ids))

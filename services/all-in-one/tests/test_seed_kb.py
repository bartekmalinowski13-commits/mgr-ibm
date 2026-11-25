"""Seeding the global knowledge-base corpus with the sample datasheets (``seed-kb``)."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from bomagent_allinone.seed_kb import seed_global_corpus
from bomagent_api.samples.catalog import SampleDatasheet, sample_datasheets
from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_kb import KnowledgeBase, extract
from bomagent_llm.embeddings import HashingEmbeddings


def _extract(name: str, data: bytes, **_: object):  # the sandbox is tested in kb-indexer
    return extract(name, data)


def _unique_copies(tmp_path: Path) -> list[SampleDatasheet]:
    """The sample datasheets with a unique last line: the test database is shared, and
    other tests index the same synthetic corpus into the global scope (same SHA-256)."""
    marker = uuid.uuid4().hex
    copies = []
    for sheet in sample_datasheets():
        path = tmp_path / sheet.path.name
        path.write_text(sheet.path.read_text(encoding="utf-8") + f"\nrun {marker}\n")
        copies.append(SampleDatasheet(path, sheet.manufacturer))
    return copies


async def test_seed_indexes_every_datasheet_once_and_every_org_can_cite_it(
    app_engine, platform_engine, make_tenant, tmp_path
):
    kb = KnowledgeBase(HashingEmbeddings())
    sheets = _unique_copies(tmp_path)
    hashes = [hashlib.sha256(s.path.read_bytes()).hexdigest() for s in sheets]

    first = await seed_global_corpus(platform_engine, kb, sheets, extractor=_extract)
    again = await seed_global_corpus(platform_engine, kb, sheets, extractor=_extract)

    assert (first.indexed, first.unchanged) == (len(sheets), 0)
    assert (again.indexed, again.unchanged) == (0, len(sheets))
    async with platform_transaction(platform_engine) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT title, manufacturer, status, created_by, tenant_id FROM kb.documents"
                    " WHERE scope = 'global' AND superseded_at IS NULL"
                    " AND sha256 = ANY(:hashes)"
                ),
                {"hashes": hashes},
            )
        ).all()
    assert len(rows) == len(sheets)
    assert {r.status for r in rows} == {"indexed"}
    assert {r.created_by for r in rows} == {"platform-pipeline"}
    assert {r.tenant_id for r in rows} == {None}
    assert {r.title: r.manufacturer for r in rows}["yageo-rc0603"] == "Yageo"

    # any organisation, including one created after the seeding, reads the corpus
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        hits = await kb.search(conn, "RC0603FR-0710KL 10 kΩ 0603", k=3)
    assert hits[0].title == "yageo-rc0603"
    assert hits[0].citation().scope == "global"


async def test_a_document_left_pending_is_indexed_on_the_next_seed(platform_engine, tmp_path):
    kb = KnowledgeBase(HashingEmbeddings())
    sheet = _unique_copies(tmp_path)[0]

    def failing(name: str, data: bytes, **_: object):
        raise RuntimeError("extractor down")

    with pytest.raises(RuntimeError):
        await seed_global_corpus(platform_engine, kb, [sheet], extractor=failing)
    sha = hashlib.sha256(sheet.path.read_bytes()).hexdigest()
    async with platform_transaction(platform_engine) as conn:
        status = (
            await conn.execute(
                text("SELECT status FROM kb.documents WHERE scope = 'global' AND sha256 = :s"),
                {"s": sha},
            )
        ).scalar()
    assert status == "pending"  # registered, not indexed

    report = await seed_global_corpus(platform_engine, kb, [sheet], extractor=_extract)

    assert (report.indexed, report.unchanged) == (1, 0)


def _seed_env(monkeypatch, db_urls, environment: str) -> None:
    for name in ("BOMAGENT_LLM_GATEWAY_URL", "BOMAGENT_LLM_GATEWAY_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOMAGENT_ENVIRONMENT", environment)
    monkeypatch.setenv("BOMAGENT_AUTH_MODE", "local")
    monkeypatch.setenv("BOMAGENT_ALLOW_FAKE_LLM", "true")
    monkeypatch.setenv("BOMAGENT_PLATFORM_DATABASE_URL", db_urls.platform)


def test_seed_kb_command_seeds_with_the_configured_embeddings(monkeypatch, db_urls, capsys):
    from bomagent_allinone.seed_kb import run

    _seed_env(monkeypatch, db_urls, "test")
    run()
    out = capsys.readouterr().out
    assert out.startswith("global corpus: ")
    assert "indexed" in out


def test_seed_kb_command_refuses_fake_embeddings_outside_local_and_test(monkeypatch, db_urls):
    from bomagent_allinone.seed_kb import run

    _seed_env(monkeypatch, db_urls, "dev")
    with pytest.raises(SystemExit, match="fake embeddings"):
        run()

"""Seeding the global knowledge-base corpus with the sample datasheets (``seed-kb``)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from bomagent_allinone.seed_kb import seed_global_corpus
from bomagent_api.samples.catalog import sample_datasheets
from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_kb import KnowledgeBase, extract
from bomagent_llm.embeddings import HashingEmbeddings


def _extract(name: str, data: bytes, **_: object):  # the sandbox is tested in kb-indexer
    return extract(name, data)


async def test_seed_indexes_every_datasheet_once_and_every_org_can_cite_it(
    app_engine, platform_engine, make_tenant
):
    kb = KnowledgeBase(HashingEmbeddings())
    sheets = sample_datasheets()

    first = await seed_global_corpus(platform_engine, kb, sheets, extractor=_extract)
    again = await seed_global_corpus(platform_engine, kb, sheets, extractor=_extract)

    assert (first.indexed, first.unchanged) == (len(sheets), 0)
    assert (again.indexed, again.unchanged) == (0, len(sheets))
    async with platform_transaction(platform_engine) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT title, manufacturer, status, created_by FROM kb.documents"
                    " WHERE scope = 'global' AND superseded_at IS NULL"
                )
            )
        ).all()
    assert len(rows) == len(sheets)
    assert {r.status for r in rows} == {"indexed"}
    assert {r.created_by for r in rows} == {"platform-pipeline"}
    by_title = {r.title: r.manufacturer for r in rows}
    assert by_title["yageo-rc0603"] == "Yageo"

    # any organisation, including one created after the seeding, reads the corpus
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        hits = await kb.search(conn, "RC0603FR-0710KL 10 kΩ 0603", k=3)
    assert hits[0].title == "yageo-rc0603"
    assert hits[0].citation().scope == "global"


async def test_a_document_left_pending_is_indexed_on_the_next_seed(platform_engine):
    kb = KnowledgeBase(HashingEmbeddings())
    sheet = sample_datasheets()[0]

    def failing(name: str, data: bytes, **_: object):
        raise RuntimeError("extractor down")

    with pytest.raises(RuntimeError):
        await seed_global_corpus(platform_engine, kb, [sheet], extractor=failing)
    report = await seed_global_corpus(platform_engine, kb, [sheet], extractor=_extract)

    assert report.indexed == 1

from __future__ import annotations

import uuid

import pytest

from bomagent_kb import KnowledgeBase
from bomagent_testing.kb import index_global_corpus, make_kb


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    return make_kb()


@pytest.fixture(scope="session")
async def global_corpus(platform_engine, kb) -> dict[str, uuid.UUID]:
    return await index_global_corpus(platform_engine, kb)

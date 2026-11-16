"""ARCH-07: the KB indexer does not silently index with hashing embeddings in hosted setups."""

from __future__ import annotations

import pytest

from bomagent_kb_indexer.app import Settings, build_handler

DB = "postgresql+asyncpg://app:pw@db.internal/bomagent"


def test_hosted_environment_without_a_gateway_is_refused():
    with pytest.raises(RuntimeError, match="BOMAGENT_LLM_GATEWAY_URL"):
        build_handler(Settings(environment="dev", database_url=DB))

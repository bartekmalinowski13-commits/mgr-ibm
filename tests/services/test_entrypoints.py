"""Every service container starts through the graceful server (SIGTERM ends live streams and
stops consumers before uvicorn waits for open connections; bounded connection drain)."""

from __future__ import annotations

import importlib

import pytest

from bomagent_common import shutdown


@pytest.mark.parametrize(
    "module",
    ["bomagent_api", "bomagent_agent_worker", "bomagent_ingest", "bomagent_kb_indexer"],
)
def test_entrypoint_uses_the_graceful_server(module, monkeypatch):
    entry = importlib.import_module(f"{module}.__main__")
    seen: list[object] = []
    monkeypatch.setattr(shutdown, "serve", seen.append)
    entry.main()
    assert seen == [entry.build_app]

"""The committed OpenAPI document is the contract (ADR-0015): it must match the code.
Regenerate with ``uv run python tools/export_openapi.py``."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.contract


def test_committed_openapi_matches_the_code():
    spec = importlib.util.spec_from_file_location(
        "export_openapi", ROOT / "tools" / "export_openapi.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = json.loads((ROOT / "services" / "api" / "openapi.json").read_text())
    assert module.openapi() == committed, "API changed: run tools/export_openapi.py and commit"
    assert committed["openapi"].startswith("3.1")

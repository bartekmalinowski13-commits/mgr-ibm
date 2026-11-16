"""Link-rot guard: relative links and backticked repo paths in the as-built docs must exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = ["docs/platform/AS_BUILT.md", "CHANGELOG.md"]
LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)#\s]+)")
CODE_PATH = re.compile(
    r"`((?:docs|services|packages|infra|deploy|tools|tests|apps|evals|\.github)/[^`\s*<>{}]+)`"
)


@pytest.mark.parametrize("name", FILES)
def test_relative_links_and_paths_exist(name: str) -> None:
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    refs = [(path.parent / m).resolve() for m in LINK.findall(text)]
    refs += [(ROOT / m.rstrip("/.,;:")).resolve() for m in CODE_PATH.findall(text)]
    missing = [str(p.relative_to(ROOT)) for p in refs if not p.exists()]
    assert not missing, f"{name} references missing paths: {sorted(set(missing))}"

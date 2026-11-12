"""Paths to shared test data (fixtures live in ``evals/fixtures``)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
FIXTURES = REPO_ROOT / "evals" / "fixtures"
KICAD_FIXTURES = FIXTURES / "kicad"
KICAD_PROJECTS = ("ecg-frontend", "pulse-ox", "eeg-2ch")


def kicad_project_paths(name: str, *, with_pro: bool = True) -> list[Path]:
    return [
        p
        for p in sorted((KICAD_FIXTURES / name).iterdir())
        if p.suffix == ".kicad_sch" or (with_pro and p.suffix == ".kicad_pro")
    ]

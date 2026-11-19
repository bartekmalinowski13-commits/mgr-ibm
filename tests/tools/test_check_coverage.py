"""tools/check_coverage.py: TESTING.md thresholds, no empty report, no drop vs the baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import check_coverage as cc


def report(tmp_path: Path, files: dict[str, tuple[int, int]]) -> Path:
    """Cobertura XML with ``files`` = {relative path: (hit lines, total lines)}."""
    classes = []
    for name, (hit, total) in files.items():
        lines = "".join(
            f'<line number="{i}" hits="{1 if i <= hit else 0}"/>' for i in range(1, total + 1)
        )
        classes.append(f'<class filename="{name}"><lines>{lines}</lines></class>')
    xml = (
        f"<coverage><sources><source>{tmp_path}</source></sources><packages><package>"
        f"<classes>{''.join(classes)}</classes></package></packages></coverage>"
    )
    path = tmp_path / "coverage.xml"
    path.write_text(xml)
    return path


GOOD = {
    "packages/py/bom/src/a.py": (90, 100),
    "packages/py/llm/src/b.py": (95, 100),
    "services/api/src/c.py": (80, 100),
}


def test_thresholds_pass(tmp_path, capsys):
    assert cc.main([str(report(tmp_path, GOOD))]) == 0
    out = capsys.readouterr().out
    assert "packages/py" in out
    assert "services/api" in out  # per package, not only the aggregate


def test_thresholds_fail(tmp_path):
    bad = GOOD | {"services/api/src/c.py": (10, 100)}
    assert cc.main([str(report(tmp_path, bad))]) == 1


def test_empty_report_fails(tmp_path, capsys):
    assert cc.main([str(report(tmp_path, {}))]) == 1
    assert "no lines" in capsys.readouterr().out


def test_a_group_without_lines_fails(tmp_path):
    only_packages = {"packages/py/bom/src/a.py": (90, 100)}
    assert cc.main([str(report(tmp_path, only_packages))]) == 1


def test_no_drop_against_the_baseline(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    xml = report(tmp_path, GOOD)
    assert cc.main([str(xml), "--write-baseline", str(baseline)]) == 0
    saved = json.loads(baseline.read_text())
    assert saved["packages/py/bom"] == pytest.approx(90.0)
    assert cc.main([str(xml), "--baseline", str(baseline)]) == 0

    dropped = report(tmp_path, GOOD | {"packages/py/bom/src/a.py": (88, 100)})
    assert cc.main([str(dropped), "--baseline", str(baseline)]) == 1
    assert "packages/py/bom" in capsys.readouterr().out


def test_small_noise_is_tolerated(tmp_path):
    baseline = tmp_path / "baseline.json"
    cc.main([str(report(tmp_path, GOOD)), "--write-baseline", str(baseline)])
    noisy = GOOD | {"packages/py/bom/src/a.py": (1798, 2000)}  # 89.9 %: within the tolerance
    assert cc.main([str(report(tmp_path, noisy)), "--baseline", str(baseline)]) == 0


def test_a_package_missing_from_the_baseline_fails(tmp_path, capsys):
    """A new package must be added to the committed baseline (reviewed by the owner), or
    it could enter with any coverage and never be held to "no drop"."""
    baseline = tmp_path / "baseline.json"
    cc.main([str(report(tmp_path, GOOD)), "--write-baseline", str(baseline)])
    new = GOOD | {"packages/py/new/src/d.py": (90, 100)}
    assert cc.main([str(report(tmp_path, new)), "--baseline", str(baseline)]) == 1
    assert "packages/py/new" in capsys.readouterr().out


def test_a_package_missing_from_the_report_fails(tmp_path):
    baseline = tmp_path / "baseline.json"
    cc.main([str(report(tmp_path, GOOD)), "--write-baseline", str(baseline)])
    gone = {k: v for k, v in GOOD.items() if "llm" not in k}
    assert cc.main([str(report(tmp_path, gone)), "--baseline", str(baseline)]) == 1


def test_the_committed_baseline_is_well_formed():
    data = json.loads(cc.DEFAULT_BASELINE.read_text())
    assert data, "tools/coverage-baseline.json must not be empty"
    assert all(k.startswith(("packages/py/", "services/")) for k in data)
    assert all(0 < v <= 100 for v in data.values())


def test_the_baseline_is_owned_by_the_owner():
    owners = (Path(__file__).resolve().parents[2] / ".github/CODEOWNERS").read_text()
    assert "/tools/coverage-baseline.json @" in owners

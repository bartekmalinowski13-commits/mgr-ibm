"""tools/ci_docs_only.py: decides whether heavy CI jobs may be skipped (OPS-07)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import ci_docs_only as cdo


def test_docs_and_markdown_only_is_docs_only():
    assert cdo.is_docs_only(["docs/STATUS.md", "docs/audit/x.md", "README.md", "CONTRIBUTING.md"])


def test_any_code_or_pipeline_file_disables_the_fast_path():
    assert not cdo.is_docs_only(["docs/STATUS.md", "services/api/src/x.py"])
    assert not cdo.is_docs_only([".github/workflows/pr.yml"])
    assert not cdo.is_docs_only(["deploy/docker/allinone.Dockerfile"])
    assert not cdo.is_docs_only(["justfile"])


def test_empty_diff_is_never_docs_only():
    assert not cdo.is_docs_only([])


def test_docs_non_markdown_assets_are_still_docs():
    assert cdo.is_docs_only(["docs/img/a.png"])


def test_path_tricks_do_not_pass():
    assert not cdo.is_docs_only(["docs/../services/x.py"])
    assert not cdo.is_docs_only(["notdocs/a.md.py"])
    assert not cdo.is_docs_only(["packages/py/cli/src/x.py", "docs/a.md"])


def test_main_reads_stdin_and_prints_flag(monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/a.md\nREADME.md\n"))
    assert cdo.main([]) == 0
    assert capsys.readouterr().out.strip() == "docs_only=true"
    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/a.md\nservices/a.py\n"))
    assert cdo.main([]) == 0
    assert capsys.readouterr().out.strip() == "docs_only=false"

"""tools/license_gate.py: AGPL/SSPL fail, unknown licences only warn (SEC-10)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import license_gate as lg


@pytest.mark.parametrize(
    "text",
    [
        "AGPL-3.0-or-later",
        "GNU Affero General Public License v3",
        "OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
        "SSPL-1.0",
        "Server Side Public License",
    ],
)
def test_network_copyleft_is_forbidden(text):
    assert lg.classify(text) == "forbidden"


@pytest.mark.parametrize(
    "text", ["MIT", "Apache-2.0 OR BSD-3-Clause", "LGPL-3.0", "MPL-2.0", "ISC"]
)
def test_other_known_licences_pass(text):
    assert lg.classify(text) == "known"


@pytest.mark.parametrize("text", ["", "Proprietary", "see LICENSE file"])
def test_unrecognised_licences_are_unknown(text):
    assert lg.classify(text) == "unknown"


def test_evaluate_splits_forbidden_unknown_and_allowed():
    pkgs = [
        lg.Package("ok", "1", "MIT"),
        lg.Package("bad", "1", "AGPL-3.0"),
        lg.Package("mystery", "1", ""),
        lg.Package("reviewed", "1", "AGPL-3.0"),
    ]
    report = lg.evaluate(pkgs, allow=["Reviewed"])
    assert [p.name for p in report.forbidden] == ["bad"]
    assert [p.name for p in report.unknown] == ["mystery"]
    assert report.checked == 4
    assert not report.ok


def test_js_parser_reads_pnpm_json():
    doc = {
        "MIT": [{"name": "react", "versions": ["19.0.0"]}],
        "AGPL-3.0": [{"name": "x", "versions": ["1.0.0", "2.0.0"]}],
    }
    pkgs = list(lg.js_packages(doc))
    assert lg.Package("x", "1.0.0, 2.0.0", "AGPL-3.0") in pkgs
    assert len(pkgs) == 2


def test_js_cli_exit_codes(capsys):
    good = json.dumps(
        {"MIT": [{"name": "a", "versions": ["1"]}], "Weird": [{"name": "b", "versions": ["1"]}]}
    )
    assert lg.main(["js"], stdin=good) == 0
    assert "WARNING" in capsys.readouterr().out
    bad = json.dumps({"SSPL-1.0": [{"name": "c", "versions": ["1"]}]})
    assert lg.main(["js"], stdin=bad) == 1
    assert lg.main(["js"], stdin="{}") == 2


def test_python_scan_runs_on_installed_environment(capsys):
    # The repo's own environment must be clean: this is the same check CI runs.
    assert lg.main(["python"]) == 0
    assert "packages checked" in capsys.readouterr().out

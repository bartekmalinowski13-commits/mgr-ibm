from __future__ import annotations

import json

from typer.testing import CliRunner

from bomagent_bom.model import BomVersion
from bomagent_cli.main import app
from bomagent_testing.data import KICAD_FIXTURES

runner = CliRunner()
ECG = KICAD_FIXTURES / "ecg-frontend"


def test_parse_summary():
    result = runner.invoke(app, ["parse", str(ECG), "--summary"])
    assert result.exit_code == 0, result.output
    assert "ecg-frontend: kicad8, 30 components, 3 sheet(s)" in result.output


def test_parse_json_to_file(tmp_path):
    out = tmp_path / "parsed.json"
    result = runner.invoke(
        app,
        [
            "parse",
            str(ECG / "ecg-frontend.kicad_sch"),
            str(ECG / "afe.kicad_sch"),
            str(ECG / "power.kicad_sch"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["source_format"] == "kicad8"


def test_parse_unsupported_file(tmp_path):
    bad = tmp_path / "board.brd"
    bad.write_bytes(b"\x00")
    result = runner.invoke(app, ["parse", str(bad)])
    assert result.exit_code == 2
    assert "unsupported.allegro_brd" in result.output


def test_bom_csv_and_json_and_eval(tmp_path):
    csv_out = tmp_path / "bom.csv"
    result = runner.invoke(app, ["bom", str(ECG), "--out", str(csv_out)])
    assert result.exit_code == 0, result.output
    assert csv_out.read_text().startswith("Line,Qty,RefDes")
    assert "mpn.present" in result.output

    req = tmp_path / "req.json"
    req.write_text('{"applied_part": "BF", "power_source": "battery"}')
    json_out = tmp_path / "bom.json"
    result = runner.invoke(
        app,
        ["bom", str(ECG), "--format", "json", "--requirements", str(req), "--out", str(json_out)],
    )
    assert result.exit_code == 0, result.output
    bom = BomVersion.model_validate_json(json_out.read_text())
    assert bom.rule_pack == "core"
    assert any(f.rule_id == "iec60601.patient_connector" for f in bom.findings)

    result = runner.invoke(app, ["eval", str(json_out), str(ECG / "reference_bom.csv")])
    assert result.exit_code == 0, result.output
    assert "| Line precision / recall / F1 | 95.5% / 100.0% /" in result.output

    known = tmp_path / "known.txt"
    known.write_text("RC0603FR-0710KL\n")
    report_out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "eval",
            str(csv_out),
            str(ECG / "reference_bom.csv"),
            "--format",
            "json",
            "--known-mpns",
            str(known),
            "--out",
            str(report_out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(report_out.read_text())["summary"]["line_recall"] == 1.0


def test_bom_rejects_unknown_format():
    result = runner.invoke(app, ["bom", str(ECG), "--format", "xml"])
    assert result.exit_code == 2


def test_bom_reports_parse_errors(tmp_path):
    bad = tmp_path / "x.kicad_sch"
    bad.write_text("(kicad_sch (version 2019))")
    result = runner.invoke(app, ["bom", str(bad)])
    assert result.exit_code == 2
    assert "kicad.legacy" in result.output

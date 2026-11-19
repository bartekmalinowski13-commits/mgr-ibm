from __future__ import annotations

import json

import pytest
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


def test_record_then_replay_with_fake_provider(tmp_path):
    cass = tmp_path / "cassettes"
    result = runner.invoke(app, ["record", str(ECG), "--cassettes", str(cass)])
    assert result.exit_code == 0, result.output
    assert list((cass / "fake-closed").glob("*.json"))
    replay = runner.invoke(app, ["run", str(ECG), "--cassettes", str(cass)])
    assert replay.exit_code == 0, replay.output


@pytest.mark.parametrize("variant", ["A", "B"])
def test_record_then_replay_with_a_real_catalogue_model(tmp_path, monkeypatch, variant):
    """I4: cassettes recorded with a real model replay with that model, without the gateway,
    byte-identical; nothing falls back to the heuristic fake."""
    import bomagent_llm.chat as chat_mod
    from bomagent_agents.fake_responder import heuristic_responder

    def answer(request):  # distinguishable from the heuristic responder's answers
        data = heuristic_responder(request)
        if request.prompt_id == "mpn_select":
            data = {**data, "rationale": "RECORDED"}
        return data

    class StubGateway(chat_mod.FakeChat):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__(answer)

    cass = tmp_path / "cassettes"
    monkeypatch.setenv("BOMAGENT_LLM_GATEWAY_URL", "http://gw")
    monkeypatch.setenv("BOMAGENT_LLM_GATEWAY_KEY", "k")
    monkeypatch.setattr(chat_mod, "GatewayChat", StubGateway)
    model = ["--model", "mistral-large-eu", "--variant", variant]
    live_out, replay_out = tmp_path / "live.json", tmp_path / "replay.json"
    rec = runner.invoke(app, ["record", str(ECG), *model, "--cassettes", str(cass)])
    assert rec.exit_code == 0, rec.output
    assert list((cass / "mistral-large-eu").glob("*.json"))
    live = runner.invoke(app, ["run", str(ECG), *model, "--cassettes", str(cass)])
    assert live.exit_code == 0, live.output

    # replay: no gateway at all - a gateway call would fail the run
    monkeypatch.delenv("BOMAGENT_LLM_GATEWAY_URL")
    monkeypatch.delenv("BOMAGENT_LLM_GATEWAY_KEY")
    monkeypatch.setattr(chat_mod, "GatewayChat", None)
    for out in (live_out, replay_out):
        res = runner.invoke(
            app, ["run", str(ECG), *model, "--cassettes", str(cass), "--out", str(out)]
        )
        assert res.exit_code == 0, res.output
        assert "completed" in res.output
    first = BomVersion.model_validate_json(live_out.read_text())
    second = BomVersion.model_validate_json(replay_out.read_text())
    assert [i.model_dump(exclude={"provenance"}) for i in first.items] == [
        i.model_dump(exclude={"provenance"}) for i in second.items
    ]
    rationales = {
        p.rationale for i in first.items for p in i.provenance.values() if p.agent == "mpn_select"
    }
    assert rationales == {"RECORDED"}


def test_replay_of_a_real_model_fails_loudly_on_a_missing_cassette(tmp_path, monkeypatch):
    from bomagent_llm.chat import CassetteMissError

    monkeypatch.delenv("BOMAGENT_LLM_GATEWAY_URL", raising=False)
    (tmp_path / "mistral-large-eu").mkdir()
    res = runner.invoke(
        app, ["run", str(ECG), "--model", "mistral-large-eu", "--cassettes", str(tmp_path)]
    )
    assert res.exit_code != 0
    assert isinstance(res.exception, CassetteMissError) or "no cassette" in res.output


def test_run_regression_thresholds_fail_the_command():
    ref = str(ECG / "reference_bom.csv")
    ok = runner.invoke(app, ["run", str(ECG), "--reference", ref, "--min-f1", "0.0"])
    assert ok.exit_code == 0, ok.output
    bad = runner.invoke(app, ["run", str(ECG), "--reference", ref, "--min-f1", "1.01"])
    assert bad.exit_code == 1
    assert "REGRESSION" in bad.output


def test_thresholds_require_reference():
    result = runner.invoke(app, ["run", str(ECG), "--min-f1", "0.5"])
    assert result.exit_code == 2


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


def test_run_variants_with_fake_provider(tmp_path):
    out = tmp_path / "bom.json"
    for variant in ("A", "B"):
        result = runner.invoke(
            app,
            [
                "run",
                str(ECG),
                "--variant",
                variant,
                "--kb-dir",
                str(KICAD_FIXTURES.parent / "datasheets"),
                "--reference",
                str(ECG / "reference_bom.csv"),
                "--out",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "MPN coverage" in result.output
        assert BomVersion.model_validate_json(out.read_text()).variant == variant
    bad = runner.invoke(app, ["run", str(ECG), "--variant", "C"])
    assert bad.exit_code == 2


def test_run_with_real_model_requires_gateway(monkeypatch):
    monkeypatch.delenv("BOMAGENT_LLM_GATEWAY_URL", raising=False)
    from bomagent_cli.main import build_chat
    from bomagent_llm.catalog import ModelNotAllowedError

    with pytest.raises(ModelNotAllowedError):  # unverified models are refused up front
        build_chat("claude-sonnet-eu", None)

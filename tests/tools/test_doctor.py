"""tools/doctor.py: toolchain check behind `just doctor` (DOC-04)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import doctor


def test_parse_version_extracts_first_dotted_number():
    assert doctor.parse_version("uv 0.11.32 (x86_64-unknown-linux-gnu)") == (0, 11, 32)
    assert doctor.parse_version("v22.23.4") == (22, 23, 4)
    assert doctor.parse_version("Python 3.12") == (3, 12)
    assert doctor.parse_version("no version here") is None


def test_check_tool_missing(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    result = doctor.check_tool(doctor.Tool("uv", ["uv", "--version"], (0, 5), "install uv"))
    assert not result.ok
    assert "missing" in result.detail
    assert result.hint == "install uv"


def test_check_tool_too_old_and_ok(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/bin/{name}")
    tool = doctor.Tool("node", ["node", "-v"], (22,), "install node 22")
    monkeypatch.setattr(doctor, "run_version", lambda _cmd: "v20.1.0")
    assert not doctor.check_tool(tool).ok
    monkeypatch.setattr(doctor, "run_version", lambda _cmd: "v22.23.4")
    assert doctor.check_tool(tool).ok


def test_check_tool_unparseable_output(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "run_version", lambda _cmd: "weird")
    result = doctor.check_tool(doctor.Tool("x", ["x"], (1,), "h"))
    assert not result.ok


def test_optional_tool_missing_is_a_warning_not_a_failure(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    tool = doctor.Tool("docker", ["docker", "--version"], (24,), "install docker", required=False)
    result = doctor.check_tool(tool)
    assert not result.ok
    assert not result.required


def test_main_exit_code_reflects_required_failures(monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    assert doctor.main([]) == 1
    out = capsys.readouterr().out
    assert "uv" in out
    assert "install" in out.lower()


def test_main_ok_when_everything_present(monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "run_version", lambda _cmd: "99.0.0")
    assert doctor.main([]) == 0
    assert "all required tools present" in capsys.readouterr().out

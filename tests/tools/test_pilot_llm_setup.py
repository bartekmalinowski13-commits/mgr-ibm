"""tools/pilot-llm-setup.sh never replaces an existing gateway master key (SEC-08 review)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "pilot-llm-setup.sh"

FLY_SHIM = r"""#!/usr/bin/env bash
echo "fly $*" >> "$SHIM_LOG"
case "$1 $2" in
  "auth whoami") exit 0 ;;
  "apps list") echo '[{"Name":"mgr-ibm-llm-gateway","Organization":{"Slug":"o"}},{"Name":"mgr-ibm-bomagent","Organization":{"Slug":"o"}}]' ;;
  "secrets list")
    [ -z "${SHIM_LIST_FAIL:-}" ] || { echo "fly: auth expired" >&2; exit 1; }
    printf '%s\n' "${SHIM_SECRETS_JSON:-[]}" ;;
  "secrets import") { echo "--- stdin of fly secrets import"; cat; } >> "$SHIM_LOG" ;;
esac
exit 0
"""


@pytest.fixture
def env(tmp_path):
    shims = tmp_path / "bin"
    shims.mkdir()
    path = shims / "fly"
    path.write_text(FLY_SHIM)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "shim.log"
    log.write_text("")
    return {
        **os.environ,
        "PATH": f"{shims}:{os.environ['PATH']}",
        "HOME": str(home),
        "SHIM_LOG": str(log),
    }


def run(env, answers: str) -> subprocess.CompletedProcess[str]:
    # prompts: Mistral key, Azure key, AWS key id, then (when asked) the confirmation
    return subprocess.run(
        ["bash", str(SCRIPT)],
        input=answers,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def imported(env) -> str:
    log = Path(env["SHIM_LOG"]).read_text()
    return log.split("--- stdin of fly secrets import")[1] if "secrets import" in log else ""


@pytest.mark.parametrize(
    "listing",
    ['[{"Name":"LITELLM_MASTER_KEY","Digest":"x"}]', '[{"name":"LITELLM_MASTER_KEY"}]'],
    ids=["Name", "lowercase name"],
)
def test_an_existing_master_key_is_kept_whatever_the_json_casing(env, listing):
    result = run({**env, "SHIM_SECRETS_JSON": listing}, "mistral-key\n\n\n")
    assert result.returncode == 0, result.stderr
    assert "LITELLM_MASTER_KEY" not in imported(env)
    assert "MISTRAL_API_KEY=mistral-key" in imported(env)
    assert list(Path(env["HOME"]).iterdir()) == []  # no vault file


def test_a_failing_secret_listing_aborts_instead_of_replacing_the_key(env):
    result = run({**env, "SHIM_LIST_FAIL": "1"}, "mistral-key\n\n\n")
    assert result.returncode != 0
    assert "secrets import" not in Path(env["SHIM_LOG"]).read_text()
    assert "could not list" in (result.stdout + result.stderr).lower()


def test_a_new_master_key_needs_an_explicit_yes_and_is_shown_once(env):
    declined = run(env, "mistral-key\n\n\nn\n")
    assert declined.returncode == 0
    assert "LITELLM_MASTER_KEY" not in imported(env)
    Path(env["SHIM_LOG"]).write_text("")
    accepted = run(env, "mistral-key\n\n\ny\n")
    assert accepted.returncode == 0, accepted.stderr
    line = next(x for x in imported(env).splitlines() if x.startswith("LITELLM_MASTER_KEY=sk-"))
    key = line.split("=", 1)[1]
    assert accepted.stdout.count(key) == 1  # shown exactly once
    assert list(Path(env["HOME"]).iterdir()) == []
